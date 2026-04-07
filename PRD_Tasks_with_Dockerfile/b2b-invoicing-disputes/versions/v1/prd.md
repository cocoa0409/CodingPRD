# Ledgerline B2B Invoicing and Disputes API

This is a B2B invoicing API where sellers can issue invoices against customer contracts and purchase orders, buyers can accept or dispute them, and payments and credits move balances around without amounts just mysteriously vanishing from the ledger.

The most important thing here is that the numbers always add up. What a buyer owes is what we billed them, minus any credits we issued, minus any payments that cleared, minus anything we explicitly wrote off. If a buyer overpays, that extra doesn’t disappear. It sits as unapplied cash on the customer until it’s used.

Everything in this API lives inside a single `workspace`. There’s no cross workspace sharing of customers, invoices, purchase orders, disputes, credits, document numbering, or idempotency keys. If two sellers both invoice the same buyer, that’s still two totally separate ledgers.

## Workspaces: one ledger, one period counter

A `workspace` is the seller’s billing universe for one legal entity. It has a currency (like `"USD"`) and it has a simple integer `period_index` that just increments from zero. In practice, `period_index` is the workspace’s posting/billing period counter.

We don’t automatically advance the period based on wall-clock time. The ledger moves forward when someone closes out a billing period by calling `POST /workspaces/{workspace_id}/advance_period`. That “period close” is when we do the end-of-period housekeeping AR teams care about: we age invoices into collections, escalate stale disputes, and trigger finance charges.

We operationalize “sits in `SENT` for a full billing period” as: the invoice must have been in `SENT` since the start of the period being closed. Concretely, on an `advance_period` call that closes period N (moves `period_index` from N to N+1), an invoice is eligible for deemed acceptance only if `status` is `SENT` and `delivered_period_index <= N - 1` (meaning it was already delivered before period N began).

Workspaces also have `books_closed_through_period_index`, which starts as `null` (nothing closed yet). When you close books, we close the most recently completed period (`period_index - 1`) and set `books_closed_through_period_index` to that value. It moves forward monotonically from there (it can never decrease).

`close_books` is **not** an idempotent “no-op if already closed” operation.

If there is no newly completed period to close (for example because `period_index` is 0, or because `books_closed_through_period_index` already equals `period_index - 1`), `POST /workspaces/{workspace_id}/close_books` fails with `ERR_INVALID_STATE_TRANSITION`.

Closing books is how teams lock down history without blocking normal day to day operations like collecting payments or resolving disputes.

Payment reversal is allowed even if books have been closed through the original payment’s posting period. Closing books blocks “rewrite history” operations like invoice voiding, but payment reversals represent external banking reality and must still be recorded.

## Who is calling this API

Every mutating request includes these headers:

`X_Actor_Id`: the caller’s user id  
`X_Actor_Role`: one of `SellerAdmin`, `SellerAR`, `BuyerAP`, `Auditor`, `System`

Seller roles:
`SellerAdmin` is like a workspace superuser: can do everything in the workspace, including overrides, freezes, closing books, voiding documents that are otherwise locked, and writing off balances.  
`SellerAR` does normal accounts receivable work: drafts invoices, finalizes and sends them, records payments, responds to disputes, and issues credits within policy.

Buyer roles:
`BuyerAP` can create purchase orders, record receipts, accept invoices, create disputes, and pay invoices (unless the customer is frozen).

Auditor:
`Auditor` is read only except for closing books; auditors usually show up around month end close and want to push the button themselves.

System:
`System` is for automation (things the platform does during period close, plus system-generated credits). External clients shouldn’t use it directly, but you’ll see it in history.

## Customers: balances, credit limits, holds, freezes

Customers are who the seller bills. A customer has:

`status`: `ACTIVE`, `CREDIT_HOLD`, `FROZEN`, `CLOSED`  
`credit_limit_cents`: the ceiling on exposure we’re willing to take (this is set explicitly)  
`balance_due_cents`: how much they currently owe (open invoice balances after credits and cleared payments)  
`unapplied_cash_cents`: money we received that isn’t allocated to invoices yet  
`available_credit_cents`: issued credits that aren’t applied yet

Those last three numbers are always meant to line up with what the customer experiences in the product. If you issue a credit, you’ll see `available_credit_cents` move immediately. If a payment clears, you’ll see either invoice balances drop or unapplied cash rise (or both if it was an overpayment).

Customer status is a mix of explicit actions and automatic behavior:

`CREDIT_HOLD` is our “slow down” state. The buyer can still pay, and disputes can still be resolved, but issuing new invoices gets restricted.

`FROZEN` is our “stop the world” state. We use it for fraud signals and payment reversals. When a customer is frozen, buyers can’t initiate new payments, they can’t open new disputes, and sellers can’t send new invoices. The goal is to stabilize the ledger first. Seller admins can still resolve disputes and issue corrective credits even while frozen.

If a customer is `FROZEN`, that wins first for buyer initiated actions that create/extend exposure (initiating payments, accepting invoices, creating purchase orders, or opening new disputes). You’ll see `ERR_CUSTOMER_FROZEN` even if the invoice is also in a weird state. Closing an existing dispute (withdraw, accept/reject resolution) is still allowed.

`CLOSED` is terminal. You can only close a customer when their ledger is clean: no open invoice balance, no unapplied cash, no available credits, and no active disputes. Closing is done explicitly via `POST /workspaces/{workspace_id}/customers/{customer_id}/close`.

### When we automatically put someone on hold

A customer is automatically moved to `CREDIT_HOLD` when any of these are true:

Their undisputed overdue exposure is above 25,000 dollars. We look across all invoices that are overdue (based on the invoice’s due period) and take only the part that isn’t disputed. If that total is more than $25,000, they’re on hold.

They have any dispute in `ESCALATED` status. Escalated disputes are serious enough that we stop new billing until someone resolves the disagreement.

Once a customer is on credit hold, they do not immediately bounce back to active. They only go back to `ACTIVE` when all of the following are true: undisputed overdue exposure is below 5,000 dollars, there are no invoices in `COLLECTIONS` stage, and there are no escalated disputes.

### When we automatically freeze someone

A customer is automatically moved to `FROZEN` when either of these happens:

A cleared payment is reversed (chargeback, clawback, bank reversal). The moment a payment becomes `REVERSED`, we freeze the customer.

A buyer opens a dispute with reason `FRAUD`.

Freezes are sticky. We intentionally avoided creating a bunch of different hold types to keep things simple. We drive everything through the customer’s `status`.

A reversal based freeze has specific duration rules. It lasts until two successful period closes (two successful calls to `advance_period`) have happened since the reversal was recorded, and there are no other reversed payments for that customer.

A fraud dispute based freeze lasts until the fraud dispute is closed (either accepted, rejected, or withdrawn) and then two successful period closes (two successful calls to `advance_period`) have happened since that closure.

Freeze status is evaluated as part of period close. On a successful `advance_period`, if the customer no longer meets any freeze condition (no active fraud dispute and all reversal/fraud cooling-off windows have elapsed), we automatically transition the customer back to `ACTIVE`. The `unfreeze` endpoint is an explicit admin action that can also be used once the customer is eligible to be unfrozen.

Seller admins can call `POST /workspaces/{workspace_id}/customers/{customer_id}/unfreeze`, but unfreeze only works if the customer is actually eligible to be unfrozen under the freeze rules. Concretely:

- For fraud-dispute freezes: there must be no currently active `FRAUD` dispute, and at least two successful period closes must have happened since the most recent fraud dispute closure.
- For reversal freezes: there must be no payment reversal still inside the two-period cooling-off window, and there must be no other reversed payments keeping the customer frozen.

If those conditions aren’t met, we keep the customer frozen and return `ERR_CUSTOMER_STILL_FROZEN`.

## Contracts: where payment terms and PO requirements come from

Invoices always reference a contract. Contracts are how we capture payment terms and billing guardrails without forcing every invoice to repeat them.

Contracts have `status`: `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATED`.

A few things we enforce because these are constant sources of downstream confusion (mostly integrations and month-end cleanups):

Only `ACTIVE` contracts can be used to finalize new invoices.

Contract status transition endpoints are not idempotent “no-op” operations. If you call `activate` on an already `ACTIVE` contract (or otherwise attempt a transition that does not make sense from the current status), we return `ERR_INVALID_STATE_TRANSITION`.

You can still create draft invoices that reference any contract. Contract status is enforced at finalize time.
Terminated contracts are dead for finalizing and sending new invoices (except the final true up invoice flow above).

Contracts also carry:

`payment_terms_periods`: how many periods after acceptance the invoice is due. We support common values like 1, 2, and 3 periods. If nothing is specified, we treat it as 2 periods.

`requires_po`: whether invoices on the contract must be tied to a purchase order.

`billing_cap_cents_per_period`: a safety cap. In a single period, the sum of invoice totals you finalize for a customer under the contract cannot exceed 100,000 dollars unless a seller admin overrides. The override mechanism is explicit on finalize: SellerAdmin can set `override_billing_cap: true` in the finalize request body to bypass the cap check.

Suspended contracts basically act like a pause button. You can still collect on existing invoices, but you can’t finalize and send new ones. Seller admins have one escape hatch: a single “final true up invoice” for a suspended or terminated contract is allowed if the invoice is 2,000 dollars or less, it doesn’t reference a purchase order, and the request explicitly marks it as a final invoice.

That last one is about catching integration bugs. Ops teams would rather stop a surprise $1,000,000 invoice than unwind it with credits later.

## Purchase orders and receipts: three way match in plain terms

Buyers create `purchase_orders` with line items. Sellers invoice against them. Buyers record receipts. This is a normal three way match flow.

Purchase orders have `status`: `OPEN`, `ACKNOWLEDGED`, `CLOSED`, `CANCELLED`.

A purchase order line has:

`ordered_units` and `unit_price_cents`  
`is_service`: if true, we don’t wait for receipts  
`received_units`: starts at zero and increases with receipts  
`net_billed_units`: how many units have been invoiced minus any credited units that were explicitly tied back to that PO line

We let receiving slightly exceed ordered units because that’s how it usually works in real life. A buyer can record receipts up to one percent above `ordered_units` per line; beyond that we reject the receipt with `ERR_RECEIPT_EXCEEDS_TOLERANCE`.

When you cancel a PO, it must have no finalized invoices tied to it. If any finalized invoice references the PO, cancellation fails with `ERR_PO_HAS_INVOICES`.

### How matching works

We treat PO numbers just like real-world POs. A `po_number` must be unique per customer while the PO is in `OPEN` or `ACKNOWLEDGED`. Once the PO is `CLOSED` or `CANCELLED`, the buyer can reuse the same number (we’ve seen that happen with some ERPs).

Invoices can reference PO lines. When they do, we compute an invoice’s `match_status` as either `MATCHED` or `EXCEPTION`. If an invoice doesn’t reference a PO at all, match status is `NOT_APPLICABLE`.

Price tolerance: per PO linked line, the invoiced unit price can be up to five percent higher than the PO unit price. Beyond that it’s an exception.

For price matching, “invoiced unit price” is evaluated on a net basis when credits are explicitly tied to that invoice line (i.e., credits that represent price adjustments for that line). Concretely, we compute an effective unit price for matching as:

- `gross_line_amount_cents = quantity_units * unit_price_cents` for the invoice line
- `credited_amount_cents = sum(credit items tied to that invoice_line_id)` (in cents)
- `net_line_amount_cents = gross_line_amount_cents - credited_amount_cents`
- `effective_unit_price_cents = floor(net_line_amount_cents / quantity_units)` (when `quantity_units > 0`)

We compare `effective_unit_price_cents` to the PO line’s `unit_price_cents` for the 5% tolerance check. Credits that are not tied to the PO-linked invoice line do not affect price matching.

Quantity tolerance: per PO linked line, the net billed units (after credits that reduce billed units) can be up to two percent above the PO ordered units. Beyond that it’s an exception.

Receipt requirement: for non service PO lines, the invoice is only considered matched for the portion that is received. Put differently: if we’ve only received 8 units, we won’t treat 10 units as fully matchable, even if the PO ordered 10. This matters for invoice acceptance and for paying undisputed balances.

Match is not a one time decision. It can change when receipts are recorded or when credits are applied. That’s intentional because that’s how operations actually work.

## Invoices: from draft to accepted to settled

Invoices are seller documents. An invoice has a `status`:

`DRAFT` means editable, no customer exposure yet  
`FINALIZED` means locked and numbered, waiting to be delivered  
`SENT` means delivered to the buyer portal  
`ACCEPTED` means the buyer accepted it (or it was deemed accepted)  
`VOIDED` means cancelled and no longer collectible  
`CLOSED` means settled (paid, credited to zero, or written off)

Invoices also expose:

`invoice_total_cents`: the total billed amount  
`amount_due_cents`: what is still owed  
`amount_disputed_cents`: what is locked behind an active dispute  
`collections_stage`: `CURRENT`, `REMINDER`, `FINAL_NOTICE`, `COLLECTIONS`  
`match_status`: `NOT_APPLICABLE`, `MATCHED`, `EXCEPTION`  
`issued_period_index`, `delivered_period_index`, `accepted_period_index`, `due_period_index`  
`reference_invoice_id`: present only when `type` is `FINANCE_CHARGE`; points at the original invoice being charged

The key relationship is this: you can’t pay more than what’s actually due and undisputed.
You also can’t accept an invoice while match exceptions remain, unless you have an active dispute that cleanly covers the exception portion.

### Drafting and finalizing

Create an invoice as a draft with `POST /workspaces/{workspace_id}/customers/{customer_id}/invoices`. Then add lines with `POST /workspaces/{workspace_id}/invoices/{invoice_id}/lines`.

Lines can optionally reference a `purchase_order_line_id`. When they do, the invoice will later participate in matching.

If an invoice references a `purchase_order_id`, then any invoice line that provides `purchase_order_line_id` must refer to a line that belongs to that same purchase order. We validate this at line-add time (`POST /workspaces/{workspace_id}/invoices/{invoice_id}/lines`). Mismatched ids are rejected with `ERR_INVALID_REQUEST`.

Finalizing an invoice is when we start treating it as a real invoice. We lock line editing, assign it a document number, set `issued_period_index` to the workspace’s current period, and compute totals. Until finalization, drafts expose `invoice_total_cents` as 0 (totals are not computed incrementally on line add).

Finalizing is where we also enforce a bunch of business guardrails in combination:

The customer must not be `CLOSED`.

The contract must be `ACTIVE` unless you’re doing the “final true up invoice” flow described earlier.

If the customer is on `CREDIT_HOLD`, finalizing normally fails with `ERR_CUSTOMER_ON_HOLD`. Seller admins can override credit hold only if the invoice is 10,000 dollars or less, the request explicitly sets `override_hold` to true, and the customer has no invoices in `COLLECTIONS`. If any of those aren’t true, the override does not apply.

If the contract requires a PO, the invoice must reference a PO in `OPEN` or `ACKNOWLEDGED` status. Otherwise finalizing fails with `ERR_PO_REQUIRED` or `ERR_PO_NOT_OPEN`.

We also block accidental duplicates. If `external_invoice_ref` is provided, it must be unique per customer across all finalized invoices that are not voided. This check happens at finalize time, not draft time, because drafts are often created and abandoned. Duplicate external ref fails with `ERR_DUPLICATE_EXTERNAL_REF`.

Accepting is not allowed if the invoice is `EXCEPTION` and there is no active dispute that covers the non matchable portion. In that case we return `ERR_MATCH_EXCEPTION`. This is how we prevent “accepting” invoices that are still missing receipts or have clear PO mismatches.

### Sending and accepting

Sending (`POST /workspaces/{workspace_id}/invoices/{invoice_id}/send`) moves a finalized invoice into `SENT` and sets `delivered_period_index`.

Acceptance (`POST /workspaces/{workspace_id}/invoices/{invoice_id}/accept`) is a buyer action. It sets `accepted_period_index` to the current period and sets `due_period_index` based on the contract payment terms.

You can only accept invoices when they’re in `SENT` status. If you call `accept` on an invoice that is already `ACCEPTED` (including deemed acceptance), the request fails with `ERR_INVALID_STATE_TRANSITION`.

If an invoice sits in `SENT` for a full billing period with no buyer action, we do a deemed acceptance at the moment the period closes (when `advance_period` is called). Deemed acceptance only happens if the invoice match status is `MATCHED` at that moment and there is no active dispute. If it’s still an exception, we do not deem accept it.

For deemed acceptance during `advance_period`, we treat the “current period” as the period being closed. Concretely: when `advance_period` moves `period_index` from N to N+1, any invoices deemed accepted in that call get `accepted_period_index = N`, and their `due_period_index` is computed from that `accepted_period_index` (i.e., `accepted_period_index + payment_terms_periods`).

### Voiding and why it’s intentionally strict

Voiding is how you correct mistakes, but not all voids are created equal.

You can void a `DRAFT` invoice anytime.

You can void a `FINALIZED` invoice only if it hasn’t been sent, it has no payments (cleared or in progress) allocated to it, it has no disputes, and the books are not closed through its `issued_period_index`. Otherwise you have to correct it with a credit memo.

You cannot void an `ACCEPTED` invoice. That’s a real obligation now. Correct it with credits.

Once books are closed through the invoice’s issue period, void is treated as rewriting history. We block it for everyone except seller admins, and even seller admins can only void if there were never any cleared payments against it.

### Collections stage

Collections stage is derived from the workspace’s current period, the invoice’s due period, and how much undisputed balance is still due.

If the invoice is not past due, stage is `CURRENT`.

Once there is undisputed overdue balance, we move it through `REMINDER`, `FINAL_NOTICE`, and then `COLLECTIONS` as it ages.

Collections teams mostly care that this is predictable, so we use a simple mapping based on how many whole periods past due the **undisputed** overdue balance is:

- `CURRENT`: not past due, or undisputed overdue balance is 0
- `REMINDER`: exactly 1 period past due with undisputed overdue balance > 0
- `FINAL_NOTICE`: exactly 2 periods past due with undisputed overdue balance > 0
- `COLLECTIONS`: 3+ periods past due with undisputed overdue balance > 0

If an invoice is fully disputed (the disputed amount covers the full current amount due), its undisputed overdue balance is 0 and its `collections_stage` is `CURRENT` regardless of how long it has been past due.

Disputes pause collections—but only for the amount disputed. The undisputed balance still moves through collections normally. If you dispute 30% of an invoice, the remaining 70% can still become overdue and enter collections.

Also, any customer with at least one invoice currently in `COLLECTIONS` is treated as `CREDIT_HOLD` for the purposes of new billing. That keeps “sent to collections” from coexisting with new invoice finalization.

## Payments: initiated, cleared, failed, reversed

Payments are how money enters the ledger. A payment has `status`:

`INITIATED`, `CLEARED`, `FAILED`, `REVERSED`

A payment can optionally specify allocations (which invoices to pay). If no allocations are provided, we auto allocate to the customer’s oldest overdue undisputed balances first.

Payments can be created by buyers (`BuyerAP`) or sellers (`SellerAR`). But if the customer is `FROZEN`, buyers cannot initiate payments. Sellers can still record payments, because sometimes money arrives anyway (wire transfers, checks).

For request validity, the sum of `allocations[].amount_cents` must be less than or equal to `amount_cents`. If allocations sum to more than the payment amount, the request is internally inconsistent and we reject it with `ERR_INVALID_REQUEST`.

Operationally, “oldest” is what AR expects (and what they’ll argue about in reconciliation threads): we sort eligible invoices by:

- `due_period_index` ascending (earliest due / most overdue first)
- then `invoice_id` ascending as a stable tie-breaker

For auto-allocation, an invoice is eligible only if it has an undisputed payable amount > 0 (`amount_due_cents - amount_disputed_cents > 0`) and it is not `VOIDED` or `CLOSED`. Auto-allocation never allocates into disputed amounts; any remainder becomes `unapplied_cash_cents` once the payment clears.

A fundamental rule you'll see everywhere: you can't pay disputed amounts. If you try to allocate into a disputed portion, we treat that part as not payable. We either leave it unapplied or reject the payment if you explicitly demanded that allocation.

While a payment is `INITIATED`, we treat its intended allocations as “spoken for.” That means other payments can’t come in and claim the same open balance. If a second payment tries to allocate into amounts already reserved by an initiated payment, we reject it with `ERR_PAYMENT_EXCEEDS_ALLOWED`.

When a payment clears, allocations become real: invoice `amount_due_cents` drops, customer `balance_due_cents` drops, and any leftover becomes `unapplied_cash_cents`.

Allocations are enforced against what is payable at the moment of clearing. If an allocation was valid when the payment was created (status `INITIATED`) but later becomes partially not payable before clearing (for example because a dispute is opened and increases `amount_disputed_cents`), then on `mark_cleared` we apply only the portion that is still undisputed/payable at clearing time. Any remainder that can’t be applied becomes `unapplied_cash_cents` when the payment clears.

For explicit allocations provided by the caller, we are strict: if any allocation amount exceeds the invoice’s undisputed payable amount (for example because part of the invoice is disputed), we reject the payment request with `ERR_PAYMENT_EXCEEDS_ALLOWED` rather than partially applying it.

When a payment fails, it never impacted balances. Any reserved allocations are released.

Payment status transition endpoints are not idempotent. `mark_failed` is only valid when the payment is currently `INITIATED`. Calling `mark_failed` when the payment is already `FAILED` (or `CLEARED` / `REVERSED`) fails with `ERR_INVALID_STATE_TRANSITION`.

When a payment is reversed, we undo what the cleared payment did. Invoices that were settled can reopen. If an early pay discount credit was created solely because of that payment (see below), we void that discount and restore the original amount due. And we freeze the customer immediately.

### Early pay discount (short pays that we intentionally allow, because Buyer AP will do it anyway)

Buyers often take early pay discounts by paying slightly less than the invoice total. We support a very specific policy because this is another common integration bug source.

If an invoice has no active disputes, has no prior credits applied, is not past due, and the buyer pays it in a single cleared payment within one period after acceptance, we allow a short pay as an early pay discount.

The discount is capped at two percent of the invoice total and never more than 500 dollars.

If a payment meets that policy, we treat the invoice as fully settled even though it was short paid. We create a system credit memo of type `EARLY_PAY_DISCOUNT` for the difference and apply it to the invoice.

If the payment is short by more than the allowed discount, we do not guess intent. The remainder stays due.

If the invoice is paid in multiple payments, the discount does not apply.

## Disputes: line level, one active at a time

Disputes are buyer initiated and always attach to a specific invoice.

A dispute has `status`:

`OPEN`, `IN_REVIEW`, `PROPOSED`, `ESCALATED`, `CLOSED`, `WITHDRAWN`

And a dispute has a `reason`:

`PRICE_MISMATCH`, `MISSING_RECEIPT`, `SERVICE_QUALITY`, `TAX_ERROR`, `DUPLICATE_INVOICE`, `FRAUD`

We only allow one active dispute per invoice. “Active” means any dispute in `OPEN`, `IN_REVIEW`, `PROPOSED`, or `ESCALATED`. If you try to create a new dispute while another is active, we return `ERR_DISPUTE_ALREADY_ACTIVE`.

Disputes can be opened while an invoice is `SENT` or `ACCEPTED` (i.e., not `VOIDED` and not `CLOSED`). Most dispute reasons have a window: they must be opened within two periods after acceptance (including deemed acceptance). `TAX_ERROR` disputes are allowed within six periods after acceptance. `FRAUD` and `DUPLICATE_INVOICE` ignore the period window, but they still require the invoice to be in a disputable lifecycle state (`SENT` or `ACCEPTED`).

If the invoice is in `COLLECTIONS`, dispute windows tighten: only `FRAUD` and `DUPLICATE_INVOICE` are allowed, regardless of periods.

When an invoice is in `COLLECTIONS`, the buyer can no longer open new disputes for normal reasons. At that point we only allow `FRAUD` and `DUPLICATE_INVOICE` disputes. Everything else returns `ERR_COLLECTIONS_RESTRICTS_DISPUTES`.

Dispute items point at invoice lines. An item can specify `disputed_units`, `disputed_amount_cents`, or both. If you provide both, they have to describe the same portion of the line. If an item disputes units, we treat it as disputing that fraction of the line total. If an item disputes cents only, we treat it as disputing that amount and do not assume any particular unit quantity.

### How disputes affect invoices, matching, and collections

While a dispute is active, the invoice’s `amount_disputed_cents` reflects the currently disputed amount. That amount is treated as not payable.

Disputes interact with matching in a very practical way: buyers can accept an invoice with match exceptions only if the parts that don’t match are actively disputed. The undisputed remainder must be matchable.

Disputes also interact with collections: disputed amounts do not drive collections stage. Undisputed amounts still do.

### Escalation and expiry on period close

A dispute has an `opened_period_index` and we track when the seller last acted.

If a dispute sits in `OPEN` for a full period without any seller response, we automatically move it to `ESCALATED` when the billing period closes (when `advance_period` is called).

If a dispute sits in `PROPOSED` and the buyer does nothing for two full periods, we automatically withdraw it on period close. We move it to `WITHDRAWN` and we void any draft credit memo that was created as part of the proposal.

We operationalize “a full period” and “two full periods” for disputes as follows:

- On an `advance_period` call that closes period N, an `OPEN` dispute is eligible to auto-escalate only if it has been open since the start of the period being closed: `opened_period_index <= N - 1`, and the seller has not responded since it was opened.
- On an `advance_period` call that closes period N, a `PROPOSED` dispute is eligible to auto-withdraw only if it has been in `PROPOSED` since the start of at least two full periods: `proposed_period_index <= N - 2`, and the buyer has taken no action since it entered `PROPOSED`.

Escalated disputes automatically put the customer on credit hold if they weren’t already.

### Seller responses and proposals

Sellers respond using `POST /workspaces/{workspace_id}/disputes/{dispute_id}/seller_respond`, which moves the dispute into `IN_REVIEW` (unless it’s already escalated, in which case it stays escalated but records the response).

Sellers propose a resolution with `POST /workspaces/{workspace_id}/disputes/{dispute_id}/propose_resolution`. A proposal can include a credit memo draft (line level credits or amount only). Proposing moves the dispute to `PROPOSED`.

Disputed totals can’t exceed what is actually still contestable. We don’t let you dispute amounts that have already been paid, already credited, already written off, or already disputed by an active dispute.

Buyers accept with `POST /workspaces/{workspace_id}/disputes/{dispute_id}/accept_resolution`. Accepting a proposal issues the draft credit memo and applies it to the invoice immediately, then closes the dispute.

Buyers reject with `POST /workspaces/{workspace_id}/disputes/{dispute_id}/reject_resolution`. Rejecting moves the dispute to `ESCALATED`.

Buyers can withdraw with `POST /workspaces/{workspace_id}/disputes/{dispute_id}/withdraw`, which sets the dispute to `WITHDRAWN` and releases the disputed amount back into payable status.

Withdrawing a dispute is allowed even if the customer is currently `FROZEN` (including freezes that were triggered by that dispute).

Even while a customer is `FROZEN`, buyers are still allowed to take actions that close an already-open dispute (withdraw it, or accept/reject a proposed resolution).

## Credits, write offs, and other corrections

A `credit_memo` is a seller issued negative document. It has `status`:

`DRAFT`, `ISSUED`, `VOIDED`

Credits can be tied to an invoice (common) or be customer level (rare but useful). Credits can also be tied to a purchase order line indirectly if the credit items reference invoice lines that referenced PO lines. That’s how `net_billed_units` gets reduced.

In API terms, creating a customer-level credit memo means omitting `invoice_id` when you create the credit memo. You can later apply that credit memo to a specific invoice via the apply endpoint.

Issuing a credit memo **always** increases the customer’s `available_credit_cents` (it creates “credit you can apply”). Issuing by itself does not change any invoice balances.

Applying credit is explicit via `POST /workspaces/{workspace_id}/credit_memos/{credit_memo_id}/apply`. Applying a credit memo reduces invoice `amount_due_cents` (and can also reduce `amount_disputed_cents` if it resolves disputed amounts). If a credit is larger than the invoice balance, the remainder stays as customer available credit.

For the purposes of `amount_disputed_cents`, a credit “resolves disputed amounts” only to the extent that the credit items are explicitly tied to invoice lines that are currently disputed by an active dispute. When a line-tied credit is applied, we reduce `amount_disputed_cents` by the credited amount that overlaps the disputed portion of those lines (capped at the current disputed amount). If a credit is not tied to the disputed lines, it reduces `amount_due_cents` but does not reduce `amount_disputed_cents`.

Applying a credit memo requires an `invoice_id` in the request body. If it’s missing, we return `ERR_INVALID_REQUEST`.

Once a credit memo has been applied (even partially), it is locked and cannot be voided. Attempting to void an applied credit memo returns `ERR_INVALID_STATE_TRANSITION`. (System-generated `EARLY_PAY_DISCOUNT` credit memos are also locked.)

There are two special cases where credits are issued and applied automatically as part of another action:

- Early pay discount: when we create a system credit memo of type `EARLY_PAY_DISCOUNT`, it is issued and applied immediately.
- Dispute resolution: accepting a proposed resolution issues the draft credit memo and applies it to the invoice as part of `POST /workspaces/{workspace_id}/disputes/{dispute_id}/accept_resolution`.

Draft credit memos from disputes have different rules. They’re controlled entirely by the dispute workflow and cannot be issued manually via `POST /workspaces/{workspace_id}/credit_memos/{credit_memo_id}/issue`. Attempting to issue a dispute-proposal draft credit memo directly fails with `ERR_INVALID_STATE_TRANSITION`.

There are guardrails because goodwill credits can be abused:

SellerAR can issue goodwill credits up to 1,000 dollars per credit memo.

Total goodwill credits issued to a single customer in a single period can’t exceed 2,500 dollars unless a seller admin issues them.

Credits tied to disputes are not treated as goodwill credits.

Credit memos created by the system for early pay discount cannot be voided manually.

### Write offs

Write offs are explicit and visible, not silent.

Writing off is done with `POST /workspaces/{workspace_id}/invoices/{invoice_id}/write_off`. It moves the invoice to `CLOSED` by writing off whatever amount due remains.

Write off is only allowed when the invoice has no active dispute and:

- The remaining amount due is 200 dollars or less and the invoice is already in `COLLECTIONS`.

If the invoice has an active dispute, `write_off` fails with `ERR_INVOICE_HAS_DISPUTE`. If any of the write-off policy constraints are not satisfied (including attempting to write off an invoice that is not in `COLLECTIONS`, or an invoice that is already `CLOSED`/settled), `write_off` fails with `ERR_WRITE_OFF_NOT_ALLOWED`.

Write offs count as a risk signal for the customer. Too many write offs in a short span tends to lead to credit holds via the exposure rules.

## Finance charges (late fees) and how they show up

Finance charges show up as regular invoices (`FINANCE_CHARGE` type) tied back to the original invoice (collections tends to treat these like “just another doc” even though they’re policy-driven).
The finance charge invoice includes `reference_invoice_id` so you can see which original invoice it is charging.

When a billing period closes (when `advance_period` is called), if an invoice had undisputed overdue balance during the period being closed, we issue a finance charge invoice for it in the new period. The close that first makes an invoice past due does not create a finance charge yet; the first finance charge comes on the next period close if it remains unpaid. The charge is one and a half percent of the undisputed overdue balance, rounded down to whole cents, never less than 25 dollars and never more than 250 dollars per original invoice per period.

We do not issue finance charges when an invoice is fully disputed (the disputed amount covers the full current amount due). If it’s partially disputed, we charge only on the undisputed overdue portion.

Finance charge invoices are sent and accepted automatically as part of the same period close. They use net 1 period terms (due in one period).

Finance charge invoices don’t represent goods/services delivery disputes, so they are not eligible for normal dispute reasons like `SERVICE_QUALITY`, `PRICE_MISMATCH`, or `MISSING_RECEIPT`. For finance charge invoices, only `FRAUD` and `DUPLICATE_INVOICE` disputes are allowed; all other dispute reasons return `ERR_DISPUTE_REASON_NOT_ALLOWED`.

There’s also a customer-level ceiling. In a single billing period, we don’t charge a customer more than **500 dollars** of finance charges total across all of their overdue invoices. If period close would create more than that, we scale down the finance charges across those invoices while keeping each invoice’s share in line with what it would have been charged that period. We round down to whole cents when we do this. If rounding leaves a few cents unassigned, we apply those leftover cents to the oldest overdue invoices first (lowest `due_period_index`, then `invoice_id` as a tie-breaker). The 25-dollar minimum and 250-dollar maximum describe the “normal” per-invoice finance charge before the customer-level ceiling applies; when the ceiling forces scaling, an individual invoice’s finance charge can end up smaller.

## Errors you’ll see (and which one wins)

The API returns error codes as JSON: `{ "error": { "code": "ERR_SOMETHING", "message": "..." } }`

If the headers are missing or malformed, we return `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the role is valid but not allowed for the endpoint, we return `ERR_FORBIDDEN_FOR_ROLE`.

When multiple things are wrong, we try to return the most actionable block.

When a void attempt is blocked by multiple conditions, we return the most specific, void-related error in this order:

1. If there is any active dispute on the invoice, return `ERR_INVOICE_HAS_DISPUTE`.
2. Else if there are any cleared or in-progress payments allocated to the invoice, return `ERR_INVOICE_HAS_PAYMENTS`.
3. Else if books are closed through the invoice’s issue period and the SellerAdmin exception does not apply, return `ERR_BOOKS_CLOSED`.
4. Otherwise return `ERR_INVALID_STATE_TRANSITION`.

A few examples that matter for integrators:

For invoice acceptance, `ERR_MATCH_EXCEPTION` wins over dispute window issues. If it doesn’t match, it doesn’t match.

For invoice finalization, credit hold wins over most other business checks. You’ll get `ERR_CUSTOMER_ON_HOLD` unless you’re using a valid override.

For dispute creation, collections restrictions win over dispute window. If the invoice is in collections, we don’t allow “normal” disputes even if you’re still within two periods.

For payments, we prefer to tell you the account is frozen (`ERR_CUSTOMER_FROZEN`) or the invoice isn’t payable (`ERR_INVOICE_NOT_PAYABLE`) before we get into the details of allocation math.

### Error code glossary (the ones tests assert)

These codes are part of the public contract. The exact HTTP status is not important here; the code is.

- `ERR_NOT_FOUND`: Any resource id that does not exist in the workspace (or is not visible in that workspace context).
- `ERR_INVALID_REQUEST`: Malformed bodies, negative/zero amounts where they don’t make sense, mismatched ids (e.g., a credit memo item referencing an invoice line that is not part of the target invoice), or other request-shape errors.
- `ERR_INVALID_STATE_TRANSITION`: The endpoint is valid, but the target resource is in a state where that transition/action is not allowed.

- `ERR_FORBIDDEN_FOR_ROLE`: Caller role is valid but not allowed for the endpoint.
- `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`: Missing/malformed `X_Actor_Id` / `X_Actor_Role`.

- `ERR_CUSTOMER_FROZEN`: Customer is `FROZEN` and the caller action is blocked by the freeze policy.
- `ERR_CUSTOMER_STILL_FROZEN`: `POST /workspaces/{workspace_id}/customers/{customer_id}/unfreeze` was attempted but the freeze-window conditions are not satisfied.
- `ERR_CUSTOMER_ON_HOLD`: Customer is on `CREDIT_HOLD` and invoice finalization is blocked (unless a valid admin override applies).
- `ERR_CUSTOMER_CLOSED`: Attempted to create new billing artifacts (like new invoices) for a customer in `CLOSED`.
- `ERR_CUSTOMER_NOT_SETTLED`: Attempted to close a customer whose ledger is not clean.

- `ERR_CONTRACT_INACTIVE`: Attempted to finalize an invoice under a contract that is not `ACTIVE`, and the “final true up invoice” exception does not apply.
- `ERR_BILLING_CAP_EXCEEDED`: Finalizing an invoice would exceed `billing_cap_cents_per_period` for that customer+contract in the current period and no admin override was used.

- `ERR_PO_REQUIRED`: Finalizing an invoice under a contract that requires a purchase order but the invoice has no purchase order.
- `ERR_PO_NOT_OPEN`: Finalizing an invoice referencing a purchase order that is not `OPEN` or `ACKNOWLEDGED`.
- `ERR_PO_HAS_INVOICES`: Attempted to cancel a purchase order that has any finalized invoices referencing it.
- `ERR_DUPLICATE_PO_NUMBER`: Attempted to create a purchase order with a `po_number` already in use for that customer while an existing PO is `OPEN` or `ACKNOWLEDGED`.
- `ERR_RECEIPT_EXCEEDS_TOLERANCE`: Attempted to record receipt units beyond the 1% over-receipt tolerance.

- `ERR_DUPLICATE_EXTERNAL_REF`: Finalizing an invoice with an `external_invoice_ref` that already exists for that customer on a finalized, non-voided invoice.
- `ERR_MATCH_EXCEPTION`: Attempted to accept an invoice while it still has match exceptions not covered by an active dispute.

- `ERR_DISPUTE_ALREADY_ACTIVE`: Attempted to open a new dispute while another dispute is active for the same invoice.
- `ERR_DISPUTE_WINDOW_CLOSED`: Attempted to open a dispute outside the allowed filing window for that reason.
- `ERR_COLLECTIONS_RESTRICTS_DISPUTES`: Attempted to open a non-`FRAUD`/non-`DUPLICATE_INVOICE` dispute while the invoice is in `COLLECTIONS`.
- `ERR_DISPUTE_AMOUNT_EXCEEDS_AVAILABLE`: Attempted to dispute more than the currently contestable amount (already paid/credited/written off/disputed portions are not contestable).
- `ERR_DISPUTE_REASON_NOT_ALLOWED`: The dispute reason is not allowed for that invoice type (e.g., finance charge invoices).
- `ERR_INVOICE_NOT_DISPUTABLE`: Invoice is not in a disputable lifecycle state for that dispute reason (e.g., already `VOIDED`/`CLOSED`).

- `ERR_PAYMENT_EXCEEDS_ALLOWED`: Payment allocations exceed what is currently payable/available (including reservations held by other initiated payments, or attempting to allocate into disputed amounts).
- `ERR_INVOICE_NOT_PAYABLE`: Attempted to allocate/pay a non-collectible invoice (e.g., `VOIDED`/`CLOSED`).
- `ERR_PERIOD_HAS_PENDING_PAYMENTS`: `POST /workspaces/{workspace_id}/close_books` attempted while the closing period has payments still in `INITIATED`.

- `ERR_CREDIT_EXCEEDS_AUTHORITY`: SellerAR attempted to issue goodwill credits beyond per-memo or per-customer-per-period caps.
- `ERR_CREDIT_MEMO_LOCKED`: Attempted to void a system-generated `EARLY_PAY_DISCOUNT` credit memo.
- `ERR_INVOICE_NOT_CREDITABLE`: Attempted to apply a credit memo to an invoice that cannot accept credits (e.g., already `CLOSED`).

- `ERR_INVOICE_HAS_PAYMENTS`: Attempted to void an invoice that has cleared or in-progress payments allocated to it.
- `ERR_INVOICE_HAS_DISPUTE`: Attempted to void or write off an invoice that still has an active dispute.
- `ERR_BOOKS_CLOSED`: Attempted to void a finalized invoice whose `issued_period_index` is within a closed-books range (unless the SellerAdmin exception applies).
- `ERR_WRITE_OFF_NOT_ALLOWED`: Attempted to write off an invoice that does not meet the write-off policy constraints.

## Idempotency

All mutating endpoints accept an optional `Idempotency_Key` header.

If you resend the exact same request (same key, path, and payload), we’ll give you the same response back.

If you reuse the same key with a different payload, or you try to reuse the key in a way that would now produce a different outcome because the ledger changed (for example the invoice was voided since the first call), we return `ERR_IDEMPOTENCY_CONFLICT`.

Idempotency keys are scoped to a workspace. Reusing the same key value in two different workspaces is allowed.

## API surface

All endpoints are under the workspace. IDs are opaque strings.

### Workspaces

`POST /workspaces`  
Request body: `{ "name": "Acme Billing", "currency": "USD" }`  
Response: `{ "workspace_id": "...", "currency": "USD", "period_index": 0, "books_closed_through_period_index": null }`

`GET /workspaces/{workspace_id}`  
Response includes the same plus `integrity_status` (`OK` or `NEEDS_REVIEW`)

`POST /workspaces/{workspace_id}/advance_period`  
Request body can be empty  
Response returns updated workspace plus a summary like `{ "period_index": 3, "finance_charge_invoice_ids": ["..."] }`

`POST /workspaces/{workspace_id}/close_books`  
Closes the most recently completed period (`period_index - 1`) and sets `books_closed_through_period_index` to that value.  
Fails with `ERR_INVALID_STATE_TRANSITION` if there is no newly completed period to close (e.g., `period_index` is 0, or `books_closed_through_period_index` already equals `period_index - 1`).  
Fails with `ERR_PERIOD_HAS_PENDING_PAYMENTS` if there are payments initiated in that period that are not yet cleared or failed.

`POST /workspaces/{workspace_id}/recompute`  
Request body can be empty.  
Recomputes derived balances and statuses. If we still can’t reconcile, returns `ERR_LEDGER_INCONSISTENT`.  
On success, response returns the updated workspace (same shape as `GET /workspaces/{workspace_id}`, including `integrity_status`).

### Customers

`POST /workspaces/{workspace_id}/customers`  
Body: `{ "display_name": "Globex", "external_customer_ref": "GLOBEX-001", "credit_limit_cents": 5000000 }`  
Response includes customer id, status, balances.

`GET /workspaces/{workspace_id}/customers/{customer_id}`  
Response includes status and balances.

`POST /workspaces/{workspace_id}/customers/{customer_id}/freeze`  
SellerAdmin only. Body: `{ "reason": "MANUAL" }`

`POST /workspaces/{workspace_id}/customers/{customer_id}/unfreeze`  
SellerAdmin only.

`POST /workspaces/{workspace_id}/customers/{customer_id}/close`  
SellerAdmin only. Fails with `ERR_CUSTOMER_NOT_SETTLED` if the ledger isn’t clean.

### Contracts

`POST /workspaces/{workspace_id}/customers/{customer_id}/contracts`  
Body: `{ "name": "MSA 2026", "payment_terms_periods": 2, "requires_po": true, "billing_cap_cents_per_period": 10000000 }`

`GET /workspaces/{workspace_id}/contracts/{contract_id}`

`POST /workspaces/{workspace_id}/contracts/{contract_id}/activate`  
SellerAdmin only.

`POST /workspaces/{workspace_id}/contracts/{contract_id}/suspend`  
SellerAdmin only.

`POST /workspaces/{workspace_id}/contracts/{contract_id}/terminate`  
SellerAdmin only.

### Purchase orders

`POST /workspaces/{workspace_id}/customers/{customer_id}/purchase_orders`  
BuyerAP or SellerAR.  
Body: `{ "po_number": "PO-1001", "lines": [ { "description": "Widgets", "ordered_units": 10, "unit_price_cents": 10000, "is_service": false } ] }`

`GET /workspaces/{workspace_id}/purchase_orders/{purchase_order_id}`

`POST /workspaces/{workspace_id}/purchase_orders/{purchase_order_id}/acknowledge`  
SellerAR or SellerAdmin.

`POST /workspaces/{workspace_id}/purchase_orders/{purchase_order_id}/record_receipt`  
BuyerAP only.  
Body: `{ "items": [ { "purchase_order_line_id": "...", "received_units": 5 } ] }`

`POST /workspaces/{workspace_id}/purchase_orders/{purchase_order_id}/cancel`  
BuyerAP only. Fails if any finalized invoice references the PO.

`POST /workspaces/{workspace_id}/purchase_orders/{purchase_order_id}/close`  
BuyerAP or SellerAdmin.

### Invoices

`POST /workspaces/{workspace_id}/customers/{customer_id}/invoices`  
SellerAR or SellerAdmin.  
Body: `{ "contract_id": "...", "purchase_order_id": "...", "external_invoice_ref": "INV-ERP-8831" }`  
Response returns invoice in `DRAFT`.

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/lines`  
Body: `{ "description": "Widgets", "quantity_units": 10, "unit_price_cents": 10000, "purchase_order_line_id": "..." }`

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/finalize`  
Body: `{ "override_hold": false, "override_billing_cap": false, "final_invoice": false }`

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/send`

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/accept`  
BuyerAP only.

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/void`  
SellerAR or SellerAdmin, rules depend on status as described.

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/write_off`  
SellerAdmin or SellerAR with policy constraints.

`GET /workspaces/{workspace_id}/invoices/{invoice_id}`  
`GET /workspaces/{workspace_id}/invoices?customer_id=...&status=...&type=...`

### Payments

`POST /workspaces/{workspace_id}/customers/{customer_id}/payments`  
Body: `{ "amount_cents": 50000, "allocations": [ { "invoice_id": "...", "amount_cents": 50000 } ] }`  
Response returns payment in `INITIATED` plus the reserved allocations and any unapplied remainder.

`POST /workspaces/{workspace_id}/payments/{payment_id}/mark_cleared`  
SellerAR or System.

`POST /workspaces/{workspace_id}/payments/{payment_id}/mark_failed`  
SellerAR or System.

`POST /workspaces/{workspace_id}/payments/{payment_id}/reverse`  
SellerAdmin only.

`GET /workspaces/{workspace_id}/payments/{payment_id}`

### Disputes

`POST /workspaces/{workspace_id}/invoices/{invoice_id}/disputes`  
BuyerAP only (and blocked when customer frozen).  
Body: `{ "reason": "MISSING_RECEIPT", "items": [ { "invoice_line_id": "...", "disputed_units": 2 } ] }`

`GET /workspaces/{workspace_id}/disputes/{dispute_id}`

`POST /workspaces/{workspace_id}/disputes/{dispute_id}/seller_respond`  
SellerAR or SellerAdmin.

`POST /workspaces/{workspace_id}/disputes/{dispute_id}/propose_resolution`  
SellerAR or SellerAdmin.  
Body example: `{ "proposed_credit": { "items": [ { "invoice_line_id": "...", "quantity_units": 2, "unit_price_cents": 10000 } ] } }`

`POST /workspaces/{workspace_id}/disputes/{dispute_id}/accept_resolution`  
BuyerAP only.

`POST /workspaces/{workspace_id}/disputes/{dispute_id}/reject_resolution`  
BuyerAP only.

`POST /workspaces/{workspace_id}/disputes/{dispute_id}/withdraw`  
BuyerAP only.

### Credit memos

`POST /workspaces/{workspace_id}/customers/{customer_id}/credit_memos`  
SellerAR or SellerAdmin.  
Body: `{ "invoice_id": "...", "reason": "GOODWILL", "items": [ { "invoice_line_id": "...", "quantity_units": 1, "unit_price_cents": 5000 } ] }`  
(`invoice_id` is optional; omit it for a customer-level credit memo.)

`POST /workspaces/{workspace_id}/credit_memos/{credit_memo_id}/issue`

`POST /workspaces/{workspace_id}/credit_memos/{credit_memo_id}/apply`  
Body: `{ "invoice_id": "..." }`

`POST /workspaces/{workspace_id}/credit_memos/{credit_memo_id}/void`

`GET /workspaces/{workspace_id}/credit_memos/{credit_memo_id}`  
`GET /workspaces/{workspace_id}/credit_memos?customer_id=...&status=...`

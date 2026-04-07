# Marquee Ticketing API (v1)

Marquee is a backend for event organizers who sell tickets through multiple sellers, move tickets between people, and still want the venue door to be calm on show night.

The product goal is simple: events can move fast (on sale, paused, closed, cancelled), but the platform never “loses track” of inventory or who holds a ticket. Most client integrations are thin: they create an event, define inventory pools, build orders, pay, and later transfer/scan admissions. The complexity sits in outcomes that always stay true: availability numbers stay accurate, sales stop when a workspace is in trouble, and tickets don’t magically become valid again once they’ve been voided.


## Workspaces and identity

Everything lives inside a workspace. Creating a workspace takes a `name` and a `settlement_currency` (like `"USD"`). Reading a workspace returns its `id`, `name`, `settlement_currency`, current `posture`, and a `version`.

Every request carries an identity and role:
- `X-Actor-Id` is the external actor making the call (a seller user id, a manager id, a gate device id, etc.).
- `X-Role` is one of `ORGANIZER`, `SELLER`, `MANAGER`, `GATE`, `AUDITOR`.

Workspaces are always in one of three postures: `OPEN`, `REVIEW`, or `HALT`.

- `OPEN` is normal operation.
- `REVIEW` is “cautious mode”: sales can continue, but checkout becomes conservative.
- `HALT` is an emergency stop: new sales and ticket movement stop, but cleanup continues — and the gate keeps scanning.


## Posture, and why it changes

Posture is derived and recalculates whenever the system’s reality changes (event lifecycle changes, orders move forward/back, capacity changes).

A workspace is `HALT` when there exists at least one cancelled event with unresolved paid orders. “Unresolved” here means an order for that event still has `status=PAID` (including any paid order that hasn’t been refunded/credited yet). Once the last paid order for cancelled events is remedied, `HALT` clears automatically.

A workspace is `REVIEW` when it is not `HALT` and any of these are true:
- any event is `PAUSED`
- any pool shows `is_overallocated: true`
- any order shows `status=APPROVAL_REQUIRED`

Otherwise the workspace is `OPEN`.

Two practical consequences matter for client integrations:
- In `REVIEW`, checkout gets conservative: any order that could take money shows up as `APPROVAL_REQUIRED` until a manager approves it.
- In `HALT`, new sales and ticket movement stop, but cleanup continues — refunds, cancels, and capacity fixes still work — and the gate keeps scanning.


## Events

Creating an event takes a `title`, a `starts_at_local` (string; informational), and a `max_tickets_per_actor` (how many valid tickets a single actor can hold for that event at once). Events have a `status` and `version`.

Event `status` moves through:
- `DRAFT` (planning; not selling)
- `ONSALE` (selling)
- `PAUSED` (sales paused)
- `CLOSED` (sales ended for good)
- `CANCELLED` (event called off; terminal)

Putting an event `ONSALE` is what allows checkout. Pausing an event pauses sales: orders can still be read and cancelled, but they can’t be submitted or paid while the event is `PAUSED`. Closing an event ends sales for good; transfers and payments stop, but scans can still happen.

Cancelling an event is bigger than “status flips to cancelled”. Cancelling an event invalidates checkout: any non-paid order for that event is cancelled automatically. Paid orders remain `PAID` until they’re remedied (refund/credit), and a cancelled event with unresolved paid orders puts the workspace in `HALT` until those orders are remedied.

Cancelling is safe to retry. Cancelling an event that is already `CANCELLED` is a no-op success: it keeps the event `CANCELLED` and does not resurrect orders or posture.


## Pools, availability, and adjustments

Pools are the sellable “buckets” of tickets within an event (GA, VIP, sponsor blocks, etc.). Creating a pool takes:
- `label`
- `kind` (`STANDARD`, `PREMIUM`, or `BOX`)
- `price_cents`
- `currency` (must match the workspace `settlement_currency`)
- `capacity_total`
- `holdback_qty` (inventory kept off the market)
- `refund_policy` (`REFUNDABLE`, `CREDIT_ONLY`, `FINAL_SALE`)
- `transfer_policy` (`OPEN`, `ONCE`, `NONE`)
- `pool_holdings_limit` (optional per-pool cap; still bounded by event cap)

Reading a pool returns the above plus `quantity_held`, `quantity_sold`, `quantity_available`, `is_overallocated`, and `version`.

Drafts don’t reserve inventory. Submit is the moment inventory is held.

Submitting an order is what places a checkout hold (`quantity_held`) on the pools. Paying converts that hold into sold inventory (`quantity_sold`). Cancel and refunds unwind those effects.

Available tickets (`quantity_available`) are whatever is left after sold tickets, checkout holds, and the pool’s `holdback_qty`. If a pool’s sold tickets plus checkout holds ever exceed sellable capacity (`capacity_total` minus `holdback_qty`), the pool shows `is_overallocated: true` and the workspace moves into `REVIEW`.

When a pool is overallocated (`is_overallocated: true`), checkout is conservatively blocked on that pool: submitting or paying an order that contains a line referencing an overallocated pool must fail with `ERR_POOL_OVERALLOCATED`.

Adjusting a pool is an explicit audit action. The adjust call takes `capacity_delta`, `holdback_delta`, an optional `new_price_cents`, and a freeform `note`.
- Capacity and holdback can move up or down, but `holdback_qty` never goes below zero.
- Capacity can’t be reduced below already-sold tickets (you can’t “take back” tickets already paid for). When an adjustment would push capacity under that floor, the adjust call fails with `ERR_CAPACITY_FLOOR`.
- Price changes (`new_price_cents`) are allowed while an event is `DRAFT` or `PAUSED`. Price changes while `ONSALE` are blocked.


## Orders: carts, holds, approvals, payments

Orders are a single-event checkout object. Creating an order includes `event_id`. The order stores `buyer_actor_id` from `X-Actor-Id`. Orders have a `status`, `lines`, `currency`, `total_cents`, optional `admission_ids` (after payment), and a `version`.

A line is expressed with `pool_id`, `quantity`, and an optional `unit_price_cents`. If `unit_price_cents` is omitted, the pool’s current `price_cents` is used as the line’s unit price. Lines are replaced atomically with the order’s lines update call. The same `pool_id` can’t appear twice in one order.

Order `status` moves through:
- `DRAFT` (editable; no inventory held)
- `SUBMITTED` (hold placed; ready to pay)
- `APPROVAL_REQUIRED` (hold placed; manager approval needed)
- `APPROVED` (hold placed; ready to pay)
- `PAID` (inventory sold; admissions issued)
- `CANCELLED` (unpaid order cancelled)
- `REFUNDED` (paid order remedied entirely by refund)
- `CREDITED` (paid order remedied entirely by credit)
- `MIXED` (paid order remedied with both refund and credit)

Submitting is the “lock and hold” moment. Paying is the “issue tickets” moment.

Submitting requires at least one line. Submitting an order with an empty `lines` list is rejected with `ERR_BAD_REQUEST`.

Manager approval is required when checkout is not routine. An order becomes `APPROVAL_REQUIRED` when submitted if any of these apply:
- workspace posture is `REVIEW`
- any line uses `unit_price_cents` that differs from the pool’s current `price_cents`
- any line references a pool with `kind=PREMIUM` or `kind=BOX`
- `total_cents` is at least 100000

In `REVIEW`, checkout gets conservative: any order that could take money shows up as `APPROVAL_REQUIRED` until a manager approves it. This applies both to newly submitted orders and to previously `SUBMITTED` orders that become “under review” as the workspace posture changes.

Paying an order issues admissions and moves pool accounting from held to sold. Paying also enforces holdings limits:
Holdings limits are about how many valid tickets an actor currently controls for an event (including tickets they received via transfer). Limits are checked when paying and when receiving transfers. A `VOIDED` admission doesn’t count toward holdings.

Refunding and crediting are how paid orders unwind. Refunds against a cancelled event are processed with `reason=EVENT_CANCELLED`, and each pool’s `refund_policy` decides whether it’s a refund or a credit. Tickets that have been scanned can’t be refunded.

After an event is `CLOSED`, voluntary “customer request” remedies stop; refunds/credits remain possible for `reason=FRAUD` and for event cancellation (`reason=EVENT_CANCELLED`).


## Admissions: transfers and gate scans

Admissions are the individual tickets issued from a paid order. Reading an admission returns `id`, `event_id`, `pool_id`, `order_id`, `holder_actor_id`, `transfer_count`, `state`, and `version`.

Admission `state` is `ACTIVE`, `SCANNED`, or `VOIDED`.

Transferring a ticket changes its `holder_actor_id` and increments `transfer_count`. Transfers are controlled by the pool’s `transfer_policy`:
- `OPEN` allows transfers while the event is `ONSALE` or `PAUSED`.
- `ONCE` allows exactly one transfer (a second transfer is blocked).
- `NONE` blocks transfers.

Closing an event ends transfers. Cancelling an event ends transfers. In workspace `REVIEW`, even `OPEN` transfers behave like “one hop” (transfers beyond `transfer_count=1` are blocked). In workspace `HALT`, ticket movement stops.

Scanning is the door action. Scanning a ticket marks it `SCANNED` and records `scanned_by_actor_id` (from `X-Actor-Id`). Scans work while an event is `ONSALE`, `PAUSED`, or `CLOSED`. Scans do not work for `DRAFT` or `CANCELLED`. In `HALT`, the gate keeps scanning.


## Consistency knobs clients rely on

Every POST expects an `Idempotency-Key`. Retrying a POST with the same `Idempotency-Key` and the same effective payload returns the original outcome. Reusing an `Idempotency-Key` with a different payload returns `ERR_IDEMPOTENCY_REPLAY_MISMATCH`.

Any call that changes an existing object expects `If-Match` with the object’s current `version`. A missing `If-Match` yields `ERR_MISSING_IF_MATCH`. A mismatched `If-Match` yields `ERR_VERSION_CONFLICT`.

When more than one issue applies, errors surface in a predictable priority: header errors, not found, role, posture, version, state, then business rules.


## Endpoints

| Method | Path | Description | Role |
|---|---|---|---|
| POST | /workspaces | Create workspace | ORGANIZER |
| GET | /workspaces/{workspace_id} | Read workspace (includes `posture`) | Any |
| POST | /workspaces/{workspace_id}/events | Create event | ORGANIZER |
| GET | /workspaces/{workspace_id}/events/{event_id} | Read event | Any |
| POST | /workspaces/{workspace_id}/events/{event_id}/on_sale | Put event on sale | ORGANIZER |
| POST | /workspaces/{workspace_id}/events/{event_id}/pause | Pause sales | ORGANIZER |
| POST | /workspaces/{workspace_id}/events/{event_id}/close | Close event | ORGANIZER |
| POST | /workspaces/{workspace_id}/events/{event_id}/cancel | Cancel event | ORGANIZER |
| POST | /workspaces/{workspace_id}/events/{event_id}/pools | Create pool | ORGANIZER |
| GET | /workspaces/{workspace_id}/events/{event_id}/pools/{pool_id} | Read pool (includes `quantity_*`) | Any |
| POST | /workspaces/{workspace_id}/events/{event_id}/pools/{pool_id}/adjust | Adjust capacity/holdback/price | ORGANIZER |
| POST | /workspaces/{workspace_id}/orders | Create order (single event) | SELLER |
| GET | /workspaces/{workspace_id}/orders/{order_id} | Read order | Any |
| PUT | /workspaces/{workspace_id}/orders/{order_id}/lines | Replace draft lines | SELLER |
| POST | /workspaces/{workspace_id}/orders/{order_id}/submit | Submit order (place hold) | SELLER |
| POST | /workspaces/{workspace_id}/orders/{order_id}/approve | Approve order | MANAGER |
| POST | /workspaces/{workspace_id}/orders/{order_id}/pay | Pay order (issue admissions) | SELLER |
| POST | /workspaces/{workspace_id}/orders/{order_id}/cancel | Cancel unpaid order | SELLER |
| POST | /workspaces/{workspace_id}/orders/{order_id}/refund | Refund/credit paid order | MANAGER |
| GET | /workspaces/{workspace_id}/admissions/{admission_id} | Read admission | Any |
| POST | /workspaces/{workspace_id}/admissions/{admission_id}/transfer | Transfer admission | SELLER, MANAGER |
| POST | /workspaces/{workspace_id}/admissions/{admission_id}/scan | Scan admission | GATE |


## Appendix: headers and errors

Required headers:
- `X-Role`
- `X-Actor-Id`
- `Idempotency-Key` (all POST)
- `If-Match` (any call that changes an existing object)

Error codes:
- ERR_BAD_REQUEST
- ERR_NOT_FOUND
- ERR_ROLE_FORBIDDEN
- ERR_MISSING_IDEMPOTENCY_KEY
- ERR_IDEMPOTENCY_REPLAY_MISMATCH
- ERR_MISSING_IF_MATCH
- ERR_VERSION_CONFLICT
- ERR_POSTURE_BLOCKED
- ERR_INVALID_STATE
- ERR_EVENT_NOT_SELLING
- ERR_LINE_EVENT_MISMATCH
- ERR_LINE_DUPLICATE
- ERR_CAPACITY_EXCEEDED
- ERR_CAPACITY_FLOOR
- ERR_CURRENCY_MISMATCH
- ERR_APPROVAL_REQUIRED
- ERR_ORDER_NOT_READY
- ERR_POOL_PRICE_CHANGE_BLOCKED
- ERR_REFUND_NOT_ALLOWED
- ERR_REMEDY_REASON_REQUIRED
- ERR_POOL_TRANSFER_BLOCKED
- ERR_NOT_HOLDER
- ERR_HOLDINGS_LIMIT_EXCEEDED
- ERR_ADMISSION_ALREADY_SCANNED
- ERR_ADMISSION_VOIDED
- ERR_SCAN_NOT_ALLOWED
- ERR_POOL_OVERALLOCATED
# Insurance Commission Accounting & Agency Billing API — Product Requirements Document

## 1. Introduction

An insurance agency operates between two ledgers that rarely agree on their own: the commission the agency expects to earn when a policy is bound, and the commission each carrier later reports on its periodic statements. Reconciling the two is complicated by advance-limited booking at bind, mid-term cancellations that claw back unearned commission, downline override hierarchies that pay upline producers a share of the writing agent's business, and the strict legal segregation of premium dollars the agency collects on a carrier's behalf and merely holds in trust. Layered on top are conduct and reporting obligations: a producer must receive a compensation disclosure before the underlying policy may bind, and year-end 1099 reporting must distinguish money actually paid to a producer from commissions earned on the books.

This document specifies the Insurance Commission Accounting & Agency Billing API, whose agency resources are mounted under `/agency`. It governs the full operating cycle — producers and their upline hierarchies, carriers and products, tiered commission schedules with effective windows, policy lifecycle from quote through voluntary or nonpayment cancellation, premium invoicing and trust remittance, carrier-statement reconciliation with variance resolution, chargeback recovery and write-off, producer payouts, and 1099 generation and finalization. Three operator roles share the workload, and a logical clock drives every time-based transition, so delinquency, grace, and lapse behavior is deterministic and testable rather than tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes three distinct roles, spelled exactly as follows: `AgencyAdmin`, `AgencyAccountant`, and `Producer`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the caller is authenticated but the role is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The `AgencyAdmin` is the agency principal and acts as a superuser: it may perform every operation in the API except disclosure acknowledgement (which is reserved to the `Producer` role per §4), and it holds exclusive control over producer termination, chargeback write-offs, trust remittance to carriers, waiving orphan statement lines, 1099 form generation and finalization, and advancement of the logical clock. The `AgencyAccountant` is the back-office operator responsible for day-to-day work: producers, carriers, products, schedules, policies, premium payments and reversals, statements and reconciliation, variance resolution, recoveries, disclosures, and payouts. The `Producer` role represents a licensed writing agent or upline producer; it has read access across the API and exactly one write capability — acknowledging its own compensation disclosure.

Identity semantics differ by role. When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same is true when `X-User-Role` is `AgencyAccountant`: an opaque operator identifier, never matched against a persisted entity. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting Producer; ownership checks on any resource that references a Producer compare the resource's producer reference field to `X-User-ID`. Concretely, acknowledging a compensation disclosure requires the caller's `X-User-ID` to equal the disclosure's `producer_id`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it reads the logical clock of §2.4.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

Requests that match no declared route — including an undeclared method on a declared path — are rejected with `ERR_NOT_FOUND` (HTTP 404) in the same envelope; an unexpected server failure surfaces in the same envelope with `error_id` `ERR_INTERNAL` and HTTP 500.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order; because every creation timestamp reads the logical clock, ties are broken by creation order — a resource created earlier always sorts before one created later.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope: `total_count` counts the filtered result set before pagination, and `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Clock

All date- and time-sensitive behavior in the system reads from a single logical clock rather than the host's wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any client has set it, the clock continues to report that default and never falls back to wall-clock time. An `AgencyAdmin` may advance the clock through an admin-only capability that accepts a target instant in the `to_iso8601` request field and returns the resulting `current_utc` in its response. The target instant is unrestricted — setting the clock to an earlier or identical instant is admitted and still fires the delinquency sweep.

Every timestamp the system stamps on a resource — disclosures, acknowledgements, matches, cancellations, payouts, finalizations — reads this logical clock as "now". Moving the clock is also the trigger for the delinquency evaluation sweep described in §3.5: each time the clock is set, invoices may flip to delinquent, policies may enter or exit grace, and grace-period policies may cancel for nonpayment, all within the same request's effects.

### 2.5. Common Resource Properties

Every resource in the system — Producer, Carrier, Product, CommissionSchedule, Policy, PremiumInvoice, CarrierStatement, CommissionEntry, Chargeback, ProducerDisclosure, ProducerPayout, and TaxForm1099 — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created, increments by one on every mutation of the resource, and backs the optimistic concurrency rules in §2.7.

Mutations performed as cascading side effects — for example the version bumps described in §3.2 and §3.8 — follow the same convention: each such mutation refreshes `updated_at` and increments `version` on the affected resource.

### 2.6. Whole-Cent Money and Rounding Discipline

All monetary amounts in the API are integers denominated in cents — fields such as `amount_cents`, `premium_annual_cents`, and `trust_balance_cents` are never fractional. Calculations that would produce a fractional cent are rounded half-up to whole cents, with zero decimal places retained.

Rounding is pinned to the individual commission entry at creation time: each entry's booked amount is rounded half-up when the entry is created, and any later total that aggregates entries — most notably the statement totals in §3.7 — sums those per-entry rounded integer values. Summing unrounded intermediate products and rounding once at the end is not the rule and will produce different cents; implementations must not do it.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent resource's `version`; no other endpoint takes a version field. On both, the `ERR_STALE_VERSION` rejection applies only to a well-formed integer that differs from the resource's current `version`; a missing or non-integer `expected_product_version` / `expected_producer_version` is instead a shape failure rejected with `ERR_INVALID_REQUEST` at step 10 of the cascade.

Creating a commission schedule requires the request to carry `expected_product_version`, holding the client last-observed `version` of the parent product. If the product's current `version` has advanced beyond what the client observed — for example because another writer has just created a superseding schedule, which legitimately retires the prior schedule and advances the product's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot price against a schedule set it has not observed.

Creating a producer payout requires the request to carry `expected_producer_version`, holding the client last-observed `version` of the producer. Because any successful payout creation, and any cascade such as chargeback-driven suspension, legitimately advances the producer's `version`, a stale value means the client's view of `commission_balance_cents` is no longer current; the create is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Trust Fund Segregation: Agency-Bill versus Direct-Bill

A policy's `billing_type` determines where its premium dollars flow. An `AGENCY_BILL` policy bills through the agency: the insured pays the agency, and every received payment lands in the issuing carrier's trust balance, tracked as `trust_balance_cents`. A `DIRECT_BILL` policy is billed by the carrier directly to the insured; its money never enters the agency's trust, no premium invoice is ever created for it, and it never participates in the delinquency sweep.

The trust is not the agency's money to keep. A carrier's trust balance equals the sum of invoice payments received on that carrier's `AGENCY_BILL` policies, minus reversed payments, minus remittances already sent; `total_remitted_cents` accumulates every remittance. Because the agency's commission is earned out of collected premium, remittances are limited by the retained-commission rule in §3.4, and payment reversals are limited by the funds still physically sitting in trust.

### 2.9. The Validation Cascade

Every request is evaluated against an ordered cascade of checks; the earliest failing check determines the error returned, and later checks do not run. The order is:

1. **Authentication context** — both headers present and the role declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the caller's role is listed for the endpoint, else `ERR_FORBIDDEN_FOR_ROLE`.
3. **Existence** — path identifiers validated left-to-right, then body foreign-key references such as `product_id`, `producer_id`, `upline_producer_id`, and `carrier_id`, else `ERR_NOT_FOUND`.
4. **State admissibility** — the target resource is in a state that allows the operation, and the optimistic-concurrency check of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`. Terminal-state lockdowns, such as paying or reversing an already `PAID` invoice, fail here.
5. **Compliance gates** — binding requires the policy's disclosure to have left the generated state (`ERR_DISCLOSURE_REQUIRED`), and payout creation requires a tax form on file (`ERR_PRODUCER_TAX_HOLD`).
6. **Temporal window rules** — schedule coverage at bind (`ERR_NO_EFFECTIVE_SCHEDULE`), schedule window overlap (`ERR_SCHEDULE_WINDOW_OVERLAP`), and statement period overlap (`ERR_STATEMENT_PERIOD_OVERLAP`).
7. **Cross-entity state** — the writing producer is active at bind and at payout events (`ERR_PRODUCER_NOT_ACTIVE`), write-off requires a terminated producer (`ERR_PRODUCER_NOT_TERMINATED`), and disclosure acknowledgement requires ownership (`ERR_NOT_RESOURCE_OWNER`).
8. **Uniqueness and aggregate constraints** — `ERR_POLICY_NUMBER_EXISTS`, `ERR_LICENSE_NUMBER_EXISTS`, `ERR_PRODUCT_CODE_EXISTS`, `ERR_UNMATCHED_STATEMENT_LINES`, and `ERR_PRODUCER_STILL_SUSPENDED`.
9. **Fiscal limits** — `ERR_OVERPAYMENT`, `ERR_NOTHING_TO_REVERSE`, `ERR_TRUST_INSUFFICIENT`, `ERR_REMIT_EXCEEDS_REMITTABLE`, `ERR_RECOVERY_EXCEEDS_OUTSTANDING`, `ERR_OUTSTANDING_CHARGEBACK`, and `ERR_PAYOUT_EXCEEDS_BALANCE`.
10. **Request shape** — required fields present, amounts positive integers, enum values valid, and `cancel_effective_date` not earlier than the policy's `effective_date`, else `ERR_INVALID_REQUEST`.

Shape checks run deliberately last so that a domain error on a known-bad target wins over a shape error; a body that cannot be parsed at all also fails at step 10. Date-valued request fields (such as `effective_date`, `effective_from`, `effective_to`, `cancel_effective_date`, `period_start`, `period_end`, and `due_date`) must be strict `YYYY-MM-DD` calendar dates, and timestamp-valued fields (such as `to_iso8601`) must be ISO 8601, failing which the request is rejected with `ERR_INVALID_REQUEST`. Compliance gates therefore outrank cross-entity state checks: on payout creation, for instance, a missing tax form surfaces as `ERR_PRODUCER_TAX_HOLD` before a non-active producer would surface as `ERR_PRODUCER_NOT_ACTIVE`.

### 2.10. Resource Addressing and Existence Order

Paths address resources directly or through a single level of nesting — for example a schedule created under its product, or an invoice listed under its policy. Where a path contains more than one identifier, the system validates identifiers sequentially from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. Body-supplied references to other resources are validated after the path identifiers, under the same error code.

## 3. Business Logic & Workflows

### 3.1. Producers and the Downline Hierarchy

A `AgencyAdmin` or `AgencyAccountant` onboards a **Producer** by supplying a `name` and a `license_number`; the license number must be unique across all producers, and a duplicate is rejected with `ERR_LICENSE_NUMBER_EXISTS`. The producer's compensation `tier` may be supplied as `STANDARD`, `GOLD`, or `PLATINUM`, defaulting to `STANDARD` when omitted. The optional `upline_producer_id` names the producer's immediate upline agency and must reference an existing producer; a null value means the producer sits at the top of its hierarchy. Chains of these references form the downline hierarchy walked at bind time in §3.3. The optional `tax_form_on_file` flag records whether a W-9 is on file; it defaults to false, and while it remains false the payout workflow of §3.8 refuses to create payouts for the producer.

A producer's `status` begins at `ACTIVE`. Two system-maintained aggregates ride on the record: `commission_balance_cents`, the earned-but-unpaid commission defined in §3.8, and `pending_chargebacks_cents`, the total still outstanding across the producer's unresolved chargebacks as defined in §3.6. When a chargeback is created and the producer's pending total crosses the suspension threshold, the system itself moves the producer from `ACTIVE` to `SUSPENDED`, incrementing the producer's `version` by one and refreshing `updated_at`; no client endpoint performs that transition directly. A suspended producer is restored to `ACTIVE` by an `AgencyAdmin` or `AgencyAccountant` through reactivation, which is admitted only from `SUSPENDED` — attempting it on a producer in any other status fails with `ERR_INVALID_STATE` — and is permitted only when the producer has no `PENDING` chargebacks remaining — otherwise the attempt is rejected with `ERR_PRODUCER_STILL_SUSPENDED`. Termination, reserved to the `AgencyAdmin`, moves a producer from `ACTIVE` to `TERMINATED` or from `SUSPENDED` to `TERMINATED`; the terminal state admits no further transitions. Terminating an active producer leaves any `PENDING` chargebacks in `PENDING` — they remain recoverable, or writable-off under §3.6, after termination.

The producer list supports filtering by `upline_producer_id`, `status`, and `tier`, alongside the standard pagination parameters.

### 3.2. Carriers, Products, and Commission Schedules

Carriers are the counterparties that pay commission. Creating a **Carrier** takes a `name` and a `carrier_code`; the code is recorded exactly as supplied and no uniqueness constraint is enforced on it. A new carrier starts with `trust_balance_cents` of zero and `total_remitted_cents` of zero, both of which move only through the trust events of §3.4.

A **Product** belongs to a carrier via its `carrier_id` and carries a `product_code`, a `name`, and a `line_of_business` drawn from `LIFE`, `ANNUITY`, `HEALTH`, or `PROPERTY_CASUALTY`. The product code must be unique within its carrier; reusing a code already present on the same carrier is rejected with `ERR_PRODUCT_CODE_EXISTS`. The product list can be filtered by `carrier_id`.

Commission pricing is expressed as **CommissionSchedule** rows created under a product. Each schedule prices exactly one producer `tier` (`STANDARD`, `GOLD`, or `PLATINUM`) and carries a `commission_rate_bps` — the first-year commission rate in basis points of annual premium, from 0 up to 10000 — an `override_rate_bps`, likewise an integer from 0 up to 10000, paid to the nearest active ancestor per §3.3, an `advance_months` count from 1 to 12 controlling how much of the first-year commission the carrier books at bind, and an effectiveness window from `effective_from` (inclusive) to `effective_to` (exclusive); a null `effective_to` leaves the window open-ended. No ordering constraint between `effective_from` and `effective_to` is enforced; an inverted window simply covers no date. The window is a half-open interval: a new schedule whose `effective_from` falls exactly on an existing same-tier schedule's `effective_to` does not overlap it. The created row starts in `ACTIVE` status, and its `product_id` is taken from the path it was created under.

Two writers may legitimately price the same product, so schedule creation participates in optimistic concurrency: the request must carry `expected_product_version`, and a stale value is rejected with `ERR_STALE_VERSION` as described in §2.7. Creating any schedule advances the parent product's `version` by one. When the request sets `supersede_existing` to true and an `ACTIVE` schedule already exists for the same product and tier, the system retires that prior schedule in the same operation — setting its `effective_to` to the new schedule's `effective_from` and moving its status to `RETIRED`, the schedule's terminal state — and that retirement itself advances the product's `version` by one as well. When `supersede_existing` is not set, a new same-tier schedule whose half-open window intersects the window of an existing `ACTIVE` same-tier schedule on the same product is rejected with `ERR_SCHEDULE_WINDOW_OVERLAP`; `RETIRED` schedules' windows never trigger this rejection. The schedule collection under a product can be filtered by `tier` and `status`.

The choice between booking variants is pinned by the schedule, not the caller: an `advance_months` of exactly 12 selects the `ANNUALIZED_FULL` variant, while any value from 1 to 11 selects `ADVANCE_LIMITED`. The consequences of that choice play out at bind time below.

### 3.3. Policy Intake, Compensation Disclosure, and Binding

A `AgencyAdmin` or `AgencyAccountant` quotes a **Policy** by supplying a `policy_number`, the `product_id` being sold, the `producer_id` of the writing agent, the `insured_name`, the `billing_type` (`AGENCY_BILL` or `DIRECT_BILL`), the `premium_annual_cents` (a positive whole-cent amount), and the `effective_date` on which coverage starts. Policy numbers are unique across the book — carrier statement lines later match on this exact string — and a duplicate is rejected with `ERR_POLICY_NUMBER_EXISTS`. A new policy starts in `QUOTED` status, with `cancel_effective_date` and `cancelled_at` null until a cancellation occurs. The policy list filters by `producer_id`, `product_id`, `status`, and `billing_type`.

Creating the policy automatically generates its **ProducerDisclosure**, one per policy, in `GENERATED` status. The disclosure's `projected_comp_cents` projects the first-year `BASE` commission for the policy at creation time, using the `ACTIVE` schedule for the product and the writing producer's tier whose window covers the policy's `effective_date`; when no such schedule exists yet, the projection is 0. An `AgencyAdmin` or `AgencyAccountant` then delivers the disclosure, moving it from `GENERATED` to `DELIVERED` and stamping `disclosed_at`. The producer personally acknowledges it — `DELIVERED` to `ACKNOWLEDGED`, stamping `acknowledged_at` — and ownership is enforced: the acknowledging caller's `X-User-ID` must equal the disclosure's `producer_id`, or the attempt is rejected with `ERR_NOT_RESOURCE_OWNER`. `ACKNOWLEDGED` is terminal. Disclosures list-filter by `policy_id`, `producer_id`, and `status`.

Binding moves a `QUOTED` policy to `ACTIVE` and is where the compliance gates of §2.9 bite. Three preconditions must hold: the writing producer's `status` is `ACTIVE`, else `ERR_PRODUCER_NOT_ACTIVE`; an `ACTIVE` schedule exists for the policy's product and the writing producer's tier whose half-open window covers the policy's `effective_date`, else `ERR_NO_EFFECTIVE_SCHEDULE`; and the policy's disclosure has reached `DELIVERED` or `ACKNOWLEDGED`, else `ERR_DISCLOSURE_REQUIRED`.

A successful bind books the expected commission as **CommissionEntry** records. The **base entry** derives from the covering schedule: first the full first-year amount is computed as the policy's `premium_annual_cents` multiplied by the schedule's `commission_rate_bps` and divided by 10000, rounded half-up to whole cents. With the `ANNUALIZED_FULL` variant (the schedule's `advance_months` is exactly 12), the entry books that full amount at bind. With the `ADVANCE_LIMITED` variant (`advance_months` below 12), the entry books the full first-year amount multiplied by `advance_months` and divided by twelve, rounded half-up — so identical policy data yields a smaller booked amount. In both variants the entry's `annualized_full_amount_cents` records the full first-year amount; under `ANNUALIZED_FULL` it equals the booked `amount_cents`, and under `ADVANCE_LIMITED` it is the informational un-discounted figure used later by the cancellation math of §3.6. The base entry is created with `entry_type` `BASE`, `status` `EXPECTED`, its `variant` pinned as selected, and references tying it to the policy, the writing producer as recipient, and the schedule used at bind via `policy_id`, `producer_id`, and `schedule_id`. Its `matched_statement_id`, `matched_at`, and `source_entry_id` are null at creation.

An **override entry** for the downline hierarchy follows. Walking the writing producer's upline chain via `upline_producer_id`, the recipient is the first ancestor whose `status` is `ACTIVE` at bind time; ancestors in `SUSPENDED` or `TERMINATED` are skipped, and when no active ancestor exists — or the schedule's `override_rate_bps` is 0 — no override entry is created at all. Otherwise the raw override is the policy's `premium_annual_cents` multiplied by `override_rate_bps` and divided by 10000, rounded half-up, and the booked override is the smaller of that raw figure and a cap equal to twenty-five percent of the base entry's booked `amount_cents`, the cap itself rounded half-up. The override entry shares the base entry's variant and `EXPECTED` status, carries `entry_type` `OVERRIDE`, names the ancestor producer as its recipient, and records an `annualized_full_amount_cents` equal to its own booked `amount_cents`.

Finally, billing type decides the paper trail. Binding an `AGENCY_BILL` policy creates its **PremiumInvoice** in `OPEN` status, with `amount_cents` equal to the policy's `premium_annual_cents` and a `due_date` exactly thirty calendar days after the policy's `effective_date`. Binding a `DIRECT_BILL` policy creates no invoice at all. Each invoice is tied to its policy through `policy_id`, and its `paid_total_cents` begins at zero.

### 3.4. Premium Collection, Trust Movements, and Remittance

Insured payments are recorded against an invoice by an `AgencyAdmin` or `AgencyAccountant`, and partial payments are allowed. Each payment's `amount_cents` must be a positive whole-cent amount (violations fail as `ERR_INVALID_REQUEST`) and must not exceed the invoice's remaining balance — its `amount_cents` minus the `paid_total_cents` already collected — or the payment is rejected with `ERR_OVERPAYMENT`. A recorded payment increases `paid_total_cents` and increases the issuing carrier's `trust_balance_cents` by the same amount, whether the invoice was `OPEN` or `DELINQUENT`. A partial payment leaves the invoice in its current status; only a payment that brings `paid_total_cents` level with `amount_cents` flips the invoice to `PAID`. When that flip happens while the owning policy sits in `GRACE` and the policy has no other `DELINQUENT` invoices, the policy returns to `ACTIVE` in the same motion. `PAID` is terminal: a further payment on a paid invoice, or an attempt to reverse a paid invoice, is rejected with `ERR_INVALID_STATE`.

Reversal is the compensating action that unwinds an invoice's payment history. It requires `paid_total_cents` to be greater than zero — otherwise there is `ERR_NOTHING_TO_REVERSE` — and requires the carrier's `trust_balance_cents` to be at least the amount being unwound, because money already remitted to the carrier cannot be pulled back; a shortfall is rejected with `ERR_TRUST_INSUFFICIENT`. A successful reversal debits the carrier's trust by the full `paid_total_cents`, resets `paid_total_cents` to zero, and leaves the invoice in the status it already held: an `OPEN` invoice stays `OPEN`, and a `DELINQUENT` invoice stays `DELINQUENT`. No grace cure is attached to unwinding; a policy driven into `GRACE` by the delinquency sweep returns to `ACTIVE` only through the payment-driven cure described in §3.5. Invoices can be listed per policy and filtered by `status`.

Periodically the agency settles trust funds with a carrier through remittance, an `AgencyAdmin`-exclusive action carrying an `amount_cents`. The remittable amount is the carrier's `trust_balance_cents` minus the retained commission, where retained commission is the sum of booked amounts across all commission entries — every entry type — in `EXPECTED` or `MATCHED` status on that carrier's `AGENCY_BILL` policies. The requested amount must be positive and no greater than the remittable amount; anything larger is rejected with `ERR_REMIT_EXCEEDS_REMITTABLE`. A successful remittance decreases `trust_balance_cents` and increases `total_remitted_cents` by the remitted amount.

### 3.5. Delinquency, Grace, and Cancellation for Nonpayment

Time only moves when the `AgencyAdmin` advances the logical clock described in §2.4, and each move fires the delinquency sweep across the book. The sweep proceeds in three steps. First, every `OPEN` invoice whose `due_date` is strictly earlier than the current date — the due date itself is still payable, so the boundary is strictly-later-than, not on-or-after — and whose `paid_total_cents` still falls short of `amount_cents` flips to `DELINQUENT`. Second, every `AGENCY_BILL` policy in `ACTIVE` status that now has a delinquent invoice moves to `GRACE`. Third, any policy in `GRACE` at that point — including a policy that entered `GRACE` in step two of the same sweep — whose oldest `DELINQUENT` invoice's `due_date` lies more than thirty days in the past cancels for nonpayment: the policy moves to `CANCELLED_NONPAY`, its `cancel_effective_date` is set to that oldest due date plus thirty days, and `cancelled_at` is stamped with the current logical time. `DIRECT_BILL` policies never enter this sweep.

Grace is curable. When a payment under §3.4 flips an invoice to `PAID` and the policy has no other `DELINQUENT` invoices, the policy moves from `GRACE` back to `ACTIVE`. Left uncured, however, the nonpayment cancellation fires the full unearned-commission cascade of §3.6 with reason `NONPAY_LAPSE`, exactly as a voluntary cancellation would.

### 3.6. Voluntary Cancellation and Unearned Commission Recovery

An `AgencyAdmin` or `AgencyAccountant` may voluntarily cancel a policy in `ACTIVE` or `GRACE` by supplying a `cancel_effective_date`; the date must not fall before the policy's `effective_date`, or the request fails with `ERR_INVALID_REQUEST`. The policy moves to `CANCELLED_VOLUNTARY` and `cancelled_at` is stamped. Both terminal states — `CANCELLED_VOLUNTARY` and the sweep-driven `CANCELLED_NONPAY` — share one cancellation cascade; they differ only in the chargeback `reason` recorded, `CANCELLATION_UNEARNED` for a voluntary cancellation and `NONPAY_LAPSE` for a lapse.

The cascade first determines how much commission was actually earned. The earned month count is the number of whole calendar months from the policy's `effective_date` to its `cancel_effective_date`: take the cancellation year minus the effective year, multiply by twelve, add the cancellation month minus the effective month, and if the cancellation day-of-month is earlier than the effective day-of-month, subtract one; the result is clamped so it never falls below zero and never exceeds twelve. For every commission entry of the policy in `EXPECTED` or `MATCHED` status, the earned portion is the entry's `annualized_full_amount_cents` multiplied by the earned month count and divided by twelve, rounded half-up to whole cents, and capped so it never exceeds the entry's own booked `amount_cents`. The unearned portion is the booked amount minus the earned portion.

Each such entry then moves to `CHARGED_BACK`, and two records fall out per entry. An `EARNED_ADJUSTMENT` entry is always created — even when the earned portion is zero — carrying the earned amount in both `amount_cents` and `annualized_full_amount_cents`, the original entry's `policy_id`, `producer_id`, `schedule_id`, and `variant`, a null `matched_statement_id`, `status` `MATCHED`, `matched_at` stamped with the current time, and `source_entry_id` pointing back to the original entry. A **Chargeback** is created only when the unearned portion is greater than zero, starting in `PENDING` status with `amount_cents` equal to the unearned portion, `recovered_cents` at zero, and `outstanding_cents` — always the amount minus what has been recovered — equal to the full amount. Each chargeback references the `policy_id`, the `producer_id` who owes the recovery, and the `commission_entry_id` being clawed back. The conservation invariant is exact: for every clawed-back entry, the chargeback's amount plus the earned-adjustment entry's amount equals the original entry's booked amount. After the entries resolve, every affected producer's derived totals recompute, and any producer still `ACTIVE` whose `PENDING` chargeback outstanding total now exceeds the suspension threshold of §3.8 is moved to `SUSPENDED`. Chargebacks list-filter by `policy_id`, `producer_id`, `commission_entry_id`, and `status`.

Recovery of a pending chargeback is recorded in cash by an `AgencyAdmin` or `AgencyAccountant`. Each recovery's `amount_cents` must be positive (else `ERR_INVALID_REQUEST`) and must not exceed the chargeback's `outstanding_cents`, or it is rejected with `ERR_RECOVERY_EXCEEDS_OUTSTANDING`. Recoveries accumulate into `recovered_cents`; the chargeback reaches `RECOVERED` exactly when `recovered_cents` equals `amount_cents`, and a partial recovery leaves it `PENDING`. When the producer has been terminated and the debt is uncollectable, an `AgencyAdmin` may write the chargeback off — but only while the chargeback's producer is `TERMINATED`; otherwise the attempt is rejected with `ERR_PRODUCER_NOT_TERMINATED`. `RECOVERED` and `WRITTEN_OFF` are both terminal.

### 3.7. Carrier Statement Reconciliation and Dispute Rework

Carriers periodically report what they actually paid. An `AgencyAdmin` or `AgencyAccountant` imports a **CarrierStatement** by supplying the `carrier_id`, a `period_start` (inclusive) and `period_end` (inclusive — the period is a closed interval; no ordering constraint between the two dates is enforced), and the statement's `lines`, an array whose elements each carry a `line_ref` holding a policy number and a `reported_amount_cents` given as any integer, zero or negative values included. Two statements of the same carrier whose closed intervals intersect — and a shared boundary date counts as an intersection — are rejected with `ERR_STATEMENT_PERIOD_OVERLAP`. A new statement starts in `RECEIVED` status; every line's computed `match_status` begins at `UNMATCHED` with a null `matched_entry_id`, and `total_reported_cents` is the sum of the lines' reported amounts.

Starting reconciliation moves the statement from `RECEIVED` to `RECONCILING` and runs the matching pass over the lines in array order. For each line, the candidate pool is the `BASE` commission entries whose policy's `policy_number` equals the line's `line_ref`, whose policy sits under the statement's carrier, and whose status is still `EXPECTED`; when several qualify, the earliest-created entry wins, and creation order guarantees no ties. If no candidate exists, the line is marked `ORPHAN`. Otherwise the line's reported amount is compared to the entry's booked amount: when the absolute difference is no more than one dollar — 100 cents — the entry moves from `EXPECTED` to `MATCHED` with `matched_statement_id` set to this statement and `matched_at` stamped, and the line is marked `MATCHED`; when the difference exceeds that tolerance, the entry moves to `VARIANCE` with its `matched_statement_id` set, and the line is marked `VARIANCE_FLAGGED`. An entry moving to `MATCHED` also causes the recipient producer's `commission_balance_cents` to recompute. Statement totals then fall out per §2.6's pinned rounding: `matched_total_cents` sums the reported amounts of `MATCHED` lines, `expected_matched_total_cents` sums the booked amounts of the linked entries — the per-entry rounded integers, never a rounding applied after summation — and `variance_total_cents` is `matched_total_cents` minus `expected_matched_total_cents`. The commission-entry ledger can be listed and filtered by `policy_id`, `producer_id`, `schedule_id`, `matched_statement_id`, `source_entry_id`, `status`, and `entry_type`; statements filter by `carrier_id` and `status`.

Reconciliation supports a rework cycle: a statement in `RECONCILING` may be flagged as `DISPUTED`, and a disputed statement may resume to `RECONCILING`; the pair may repeat without bound while differences are argued with the carrier.

Two resolution paths clear the leftovers. A `VARIANCE` entry is resolved by an `AgencyAdmin` or `AgencyAccountant` accepting the carrier-reported figure via `accept_amount_cents`, which must be zero or greater (a negative value fails with `ERR_INVALID_REQUEST`). Resolution requires only that the entry sit in `VARIANCE`; the linked statement's own status is not re-checked. The original entry's booked amount is immutable and does not change; instead the entry moves from `VARIANCE` to `MATCHED` with `matched_at` stamped, the flagging statement line moves from `VARIANCE_FLAGGED` to `MATCHED`, and a `VARIANCE_ADJUSTMENT` entry is created with `status` `MATCHED`, `matched_at` stamped with the current time, a null `matched_statement_id`, the resolved entry's `policy_id`, `producer_id`, `schedule_id`, and `variant`, an `annualized_full_amount_cents` equal to the adjustment amount, `source_entry_id` pointing at the resolved entry, and an `amount_cents` equal to the accepted amount minus the original booked amount — negative when the agency accepts less than it booked. When that adjustment is negative, a `PENDING` chargeback is created with `reason` `OVERPAYMENT_VARIANCE` for the absolute shortfall, and the producer-suspension check of §3.8 runs on the result. Separately, an `AgencyAdmin` may waive an `ORPHAN` line by naming its `line_ref`, moving the line to `WAIVED`; a `line_ref` matching no line of the statement is rejected with `ERR_NOT_FOUND`, waiving is admitted only while the statement is `RECONCILING` or `DISPUTED`, and naming a line whose `match_status` is not `ORPHAN` fails with `ERR_INVALID_STATE`.

Closing reconciliation — moving the statement from `RECONCILING` to `RECONCILED` — is permitted only when every line's `match_status` is `MATCHED` or `WAIVED` and no commission entry linked to this statement remains in `VARIANCE`; otherwise the close is rejected with `ERR_UNMATCHED_STATEMENT_LINES`. A successful close freezes the statement's `matched_total_cents`, `expected_matched_total_cents`, and `variance_total_cents`, and `RECONCILED` is terminal.

### 3.8. Producer Balances, Payouts, and the Suspension Circuit

A producer's `commission_balance_cents` is the earned-but-unpaid ledger position: the sum of `amount_cents` over every commission entry — of any entry type — for which the producer is the recipient and the status is `EXPECTED` or `MATCHED`, minus the sum of `amount_cents` over the producer's payouts already in `PAID` status. The companion aggregate `pending_chargebacks_cents` sums `outstanding_cents` over the producer's chargebacks still in `PENDING` status. Both recompute whenever an entry, payout, or chargeback involving the producer mutates.

The suspension circuit guards the agency against runaway clawbacks. Immediately after any chargeback is created — from the cancellation cascade of §3.6 or the variance resolution of §3.7 — if the producer's `PENDING` chargeback outstanding total is strictly greater than $5,000.00 (500000 cents) and the producer is still `ACTIVE`, the system moves the producer to `SUSPENDED`, incrementing the producer's `version` and refreshing `updated_at`. A suspended producer blocks new business: binding a policy they wrote fails with `ERR_PRODUCER_NOT_ACTIVE`, payout events fail the same way, and reactivation requires the chargeback queue to be fully cleared per §3.1.

Paying a producer is a two-step flow with checks at both steps. Creating a payout requires `amount_cents` and the OCC field `expected_producer_version` of §2.7, and its business checks run in the cascade order of §2.9: the producer's `status` must be `ACTIVE` or the request fails with `ERR_PRODUCER_NOT_ACTIVE`; the producer's `tax_form_on_file` must be true, else `ERR_PRODUCER_TAX_HOLD`; the producer must have no `PENDING` chargebacks at all, else `ERR_OUTSTANDING_CHARGEBACK`; and the amount must not exceed the producer's `commission_balance_cents` at that moment, else `ERR_PAYOUT_EXCEEDS_BALANCE`. A created payout starts in `INITIATED` status, and its creation advances the producer's `version` by one. Marking the payout paid re-verifies the producer's position at that moment — the producer must still be `ACTIVE` (else `ERR_PRODUCER_NOT_ACTIVE`) and the payout amount must still fit within the current `commission_balance_cents` (else `ERR_PAYOUT_EXCEEDS_BALANCE`) — then moves the payout from `INITIATED` to `PAID`, stamps `paid_at` with the logical clock's current instant, and subtracts the amount from the producer's balance. That `paid_at` instant is what later places the payout inside a 1099 tax year in §3.9. Payouts list-filter by `producer_id` and `status`.

### 3.9. Year-End Producer Compensation Reporting (1099)

At year end the agency owes each sufficiently-paid producer a **TaxForm1099**, and the form deliberately carries two views of compensation. The `cash_basis_total_cents` sums the `amount_cents` of the producer's payouts in `PAID` status whose `paid_at` falls within the tax year — from January 1 of the `tax_year` inclusive up to but excluding January 1 of the following year. The `accrual_basis_total_cents` sums the `amount_cents` of the producer's commission entries in `MATCHED` status whose `matched_at` falls within the tax year, across all entry types, including negative `VARIANCE_ADJUSTMENT` amounts. Identical producer data therefore yields two different totals on the same form: cash actually paid versus commissions matched against carrier statements.

Generation is an `AgencyAdmin`-exclusive action taking a `tax_year`. A `DRAFT` form is created for a producer exactly when that producer's cash-basis total for the year is at least $600.00 (60000 cents — a total of 59999 cents does not qualify) and no form in any status already exists for that producer and year; producers below the threshold or already holding a form are skipped. The response reports `generated_count` alongside the `tax_form_ids` created. Generation snapshots nothing: while a form remains `DRAFT`, its two totals are recomputed from current data on every read, so they drift with subsequent payouts and entry matches until finalization locks them. Forms list-filter by `producer_id`, `tax_year`, and `status`.

Finalization, also exclusive to `AgencyAdmin`, moves a form from `DRAFT` to `FINALIZED`: both totals are recomputed as of that moment, locked against further drift, and `finalized_at` is stamped. `FINALIZED` is terminal — the locked figures are what the agency reports.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a producer, carrier, product, commission schedule, policy, carrier statement, or payout — return a `201 Created` status code. Operations that modify an existing resource or drive a state transition — binding, cancelling, paying, reversing, remitting, reconciling, resolving, recovering, delivering, acknowledging, marking paid, generating, finalizing, reactivating, terminating, and setting the clock — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (fires the delinquency sweep) | AgencyAdmin |
| POST | `/agency/producers` | Create a producer | AgencyAdmin, AgencyAccountant |
| GET | `/agency/producers` | List producers | All roles |
| GET | `/agency/producers/{producerId}` | Get a producer | All roles |
| POST | `/agency/producers/{producerId}/reactivate` | Reactivate a SUSPENDED producer | AgencyAdmin, AgencyAccountant |
| POST | `/agency/producers/{producerId}/terminate` | Terminate a producer | AgencyAdmin |
| POST | `/agency/producers/{producerId}/payouts` | Create a payout (OCC on Producer version) | AgencyAdmin, AgencyAccountant |
| GET | `/agency/payouts/{payoutId}` | Get a payout | All roles |
| GET | `/agency/payouts` | List payouts | All roles |
| POST | `/agency/payouts/{payoutId}/mark-paid` | Mark a payout as PAID | AgencyAdmin, AgencyAccountant |
| POST | `/agency/carriers` | Create a carrier | AgencyAdmin, AgencyAccountant |
| GET | `/agency/carriers/{carrierId}` | Get a carrier | All roles |
| POST | `/agency/carriers/{carrierId}/remit` | Remit trust funds to the carrier | AgencyAdmin |
| POST | `/agency/products` | Create a product | AgencyAdmin, AgencyAccountant |
| GET | `/agency/products` | List products | All roles |
| GET | `/agency/products/{productId}` | Get a product | All roles |
| POST | `/agency/products/{id}/commission-schedules` | Create a commission schedule (OCC on Product version) | AgencyAdmin, AgencyAccountant |
| GET | `/agency/products/{id}/commission-schedules` | List schedules of a product | All roles |
| GET | `/agency/commission-schedules/{scheduleId}` | Get a schedule | All roles |
| POST | `/agency/policies` | Create a policy in QUOTED with its disclosure | AgencyAdmin, AgencyAccountant |
| GET | `/agency/policies` | List policies | All roles |
| GET | `/agency/policies/{policyId}` | Get a policy | All roles |
| POST | `/agency/policies/{policyId}/bind` | Bind a QUOTED policy | AgencyAdmin, AgencyAccountant |
| POST | `/agency/policies/{policyId}/cancel` | Voluntarily cancel an ACTIVE or GRACE policy | AgencyAdmin, AgencyAccountant |
| GET | `/agency/policies/{id}/invoices` | List invoices of a policy | All roles |
| GET | `/agency/premium-invoices/{invoiceId}` | Get an invoice | All roles |
| POST | `/agency/premium-invoices/{invoiceId}/payments` | Record an insured premium payment (partial allowed) | AgencyAdmin, AgencyAccountant |
| POST | `/agency/premium-invoices/{invoiceId}/reverse-payments` | Reverse all payments on an invoice | AgencyAdmin, AgencyAccountant |
| POST | `/agency/carrier-statements` | Import a carrier statement | AgencyAdmin, AgencyAccountant |
| GET | `/agency/carrier-statements` | List statements | All roles |
| GET | `/agency/carrier-statements/{statementId}` | Get a statement | All roles |
| POST | `/agency/carrier-statements/{statementId}/start-reconciliation` | Match lines against EXPECTED entries | AgencyAdmin, AgencyAccountant |
| POST | `/agency/carrier-statements/{statementId}/dispute` | Flag the statement as disputed | AgencyAdmin, AgencyAccountant |
| POST | `/agency/carrier-statements/{statementId}/resume` | Resume reconciliation after a dispute | AgencyAdmin, AgencyAccountant |
| POST | `/agency/carrier-statements/{statementId}/close` | Close reconciliation (requires zero unresolved lines) | AgencyAdmin, AgencyAccountant |
| POST | `/agency/carrier-statements/{statementId}/waive-line` | Waive an ORPHAN statement line | AgencyAdmin |
| GET | `/agency/commission-entries` | List commission entries | All roles |
| GET | `/agency/commission-entries/{entryId}` | Get a commission entry | All roles |
| POST | `/agency/commission-entries/{entryId}/resolve-variance` | Accept the carrier-reported amount for a VARIANCE entry | AgencyAdmin, AgencyAccountant |
| GET | `/agency/chargebacks` | List chargebacks | All roles |
| GET | `/agency/chargebacks/{chargebackId}` | Get a chargeback | All roles |
| POST | `/agency/chargebacks/{chargebackId}/recoveries` | Record a recovery payment against a chargeback | AgencyAdmin, AgencyAccountant |
| POST | `/agency/chargebacks/{chargebackId}/write-off` | Write off a chargeback (producer must be TERMINATED) | AgencyAdmin |
| GET | `/agency/producer-disclosures` | List disclosures | All roles |
| GET | `/agency/producer-disclosures/{disclosureId}` | Get a disclosure | All roles |
| POST | `/agency/producer-disclosures/{disclosureId}/deliver` | Deliver the disclosure to the producer | AgencyAdmin, AgencyAccountant |
| POST | `/agency/producer-disclosures/{disclosureId}/acknowledge` | Producer acknowledges their own disclosure | Producer |
| POST | `/agency/tax-forms/generate` | Generate DRAFT 1099 forms for qualifying producers | AgencyAdmin |
| GET | `/agency/tax-forms` | List 1099 forms | All roles |
| GET | `/agency/tax-forms/{formId}` | Get a 1099 form | All roles |
| POST | `/agency/tax-forms/{formId}/finalize` | Finalize a 1099 form (recompute and lock totals) | AgencyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_NUMBER_EXISTS` | 409 Conflict |
| `ERR_LICENSE_NUMBER_EXISTS` | 409 Conflict |
| `ERR_PRODUCT_CODE_EXISTS` | 409 Conflict |
| `ERR_PRODUCER_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRODUCER_NOT_TERMINATED` | 409 Conflict |
| `ERR_PRODUCER_STILL_SUSPENDED` | 409 Conflict |
| `ERR_DISCLOSURE_REQUIRED` | 409 Conflict |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_PRODUCER_TAX_HOLD` | 409 Conflict |
| `ERR_NO_EFFECTIVE_SCHEDULE` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_OVERPAYMENT` | 409 Conflict |
| `ERR_NOTHING_TO_REVERSE` | 409 Conflict |
| `ERR_TRUST_INSUFFICIENT` | 409 Conflict |
| `ERR_REMIT_EXCEEDS_REMITTABLE` | 409 Conflict |
| `ERR_UNMATCHED_STATEMENT_LINES` | 409 Conflict |
| `ERR_RECOVERY_EXCEEDS_OUTSTANDING` | 409 Conflict |
| `ERR_OUTSTANDING_CHARGEBACK` | 409 Conflict |
| `ERR_PAYOUT_EXCEEDS_BALANCE` | 409 Conflict |
| `ERR_INTERNAL` | 500 Internal Server Error |

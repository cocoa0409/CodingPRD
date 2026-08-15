# Rural Water District API — Product Requirements Document

## 1. Introduction

Rural water districts occupy an unusual position in American utility governance: they are member-owned cooperatives, often operating under a USDA Rural Development loan, with a volunteer board, a part-time office, and a regulatory burden out of proportion to their headcount. The work is cyclical and unforgiving. Every month the district reads meters, bills members against a board-adopted rate schedule, ages delinquent accounts, posts a legally mandated deposit into a debt-service reserve, and reconciles what the master meter says was produced against what the tap meters say was sold. On top of that rhythm sit episodic obligations — boil orders that demand documented notification of every active member before sampling may begin, annexation petitions with refundable deposits, and board resolutions whose votes must be recorded with segregation of duties preserved.

This document specifies a REST API for operating such a district end to end: membership applications, tap connections and meter installation, monthly billing with a minimum-plus-tier rate structure, payment collection with overpayment credit, delinquency escalation through disconnect and reconnection, master-meter water-loss reconciliation, USDA reserve covenant tracking, boil-order notification and sampling compliance, service-area annexation, and board governance. All monetary amounts are integer cents; all timestamps are governed by a server-side logical clock rather than wall-clock time, so that delinquency aging and sampling windows are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is valid but not permitted for the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Five roles exist, spelled exactly as follows: `SystemAdmin`, `BillingClerk`, `Treasurer`, `BoardDirector`, and `FieldOperator`. For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, to attribute a recorded vote on a `BoardResolution` to a specific board member, or to attribute a billing run to the clerk who initiated it) but it never compares the value to any entity's `id`.

Two segregation-of-duties constraints cut across the role list and are enforced with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). First, the same `X-User-ID` may not both bill a cycle and post a payment against that cycle's invoices — billing and collecting are segregated duties even though the role names already differ, because the rule is keyed on the operator identifier, not the role. Second, the `BoardDirector` who proposed a resolution may not record the deciding vote on it.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
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

### 2.3. Pagination

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Out-of-range or malformed pagination values are not errors: a non-integer `limit` or `offset` falls back to its default, `limit` is clamped into [1, 100], and `offset` is floored at 0. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope, with `has_more` true exactly when `offset` plus the number of items on the returned page is less than `total_count`. Default sort order on every list endpoint is `created_at` ascending, ties broken by insertion order. Many list endpoints additionally accept exact-match query filters on resource fields: districts filter by `active_rate_schedule_id`; members by `membership_status` and `service_area_id`; taps by `member_id` and `status`; billing cycles by `status`; meter readings by `tap_id` and `cycle_id`; master meter readings by `cycle_id`; invoices by `member_id`, `cycle_id`, `billing_status`, and `collection_status`; payments by `member_id`, `invoice_id`, and `status`; reserve entries by `entry_type` and `cycle_id`; rate schedules by `status`; board resolutions by `resolution_type` and `status`; annexation petitions by `status`; boil orders by `status`; and compliance samples by `boil_order_id` and `result`.

### 2.4. Common Resource Properties and the Logical Clock

Most persisted resources share four properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits; `updated_at`, stamped the same way and refreshed on every mutation; and `version`, an integer that increments by 1 on every mutation of the resource. Four resource kinds are lighter-weight ledger-style records and carry only `id` and `created_at` — `MeterReading`, `MasterMeterReading`, `ReserveEntry`, and `NotificationReceipt` expose neither `updated_at` nor `version`.

The server maintains a logical clock, distinct from wall-clock time. Before any clock call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. An administrative capability, available to all five roles, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The supplied instant is accepted without comparison against the current reading — the clock may be set to any valid ISO 8601 instant — and the returned `current_utc` echoes the supplied string verbatim. Delinquency aging, boil-order issuance stamps, sampling windows, and notification deadlines all read from this clock; advancing the clock does not itself re-run delinquency escalation, which is re-evaluated lazily at the next bill cascade or explicit notice issuance.

### 2.5. Money, Precision, and Rounding

All money is integer cents — fields such as `base_minimum_cents`, `tap_fee_cents`, `amount_cents`, and `reserve_balance_cents` never carry fractional values. Percentages used in water-loss reporting (`provisional_loss_pct`, `final_loss_pct`) are numbers with 3 decimal places, rounded half-up. Where a percentage-of-deposit calculation produces a fractional cent (the annexation feasibility fee), the percentage leg is rounded half-up to integer cents before any further comparison. The ratio used in covenant evaluation (the withdrawal floor) is exact rational arithmetic; the money it compares against remains integer cents. The tiered usage charge rounds each tier's started-thousand quantity up before summing across tiers — rounding order is pinned as round-per-tier-then-sum, and reordering it changes results.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the `District` aggregate's `version`.

Closing a billing cycle requires the request to carry `expected_district_version`, the client's last observed `version` of the district. If the district's current `version` has advanced since that observation — for example because another writer billed a later cycle, adopted a resolution, or issued a boil order — the close is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because closing mutates `reserve_balance_cents`, `covenant_status`, `current_billing_epoch`, and every member's `consecutive_delinquent_cycles`; posting a reserve ledger entry against an obsolete balance would corrupt the covenant trail.

Proposing a board resolution is the second guarded write. A proposal request may carry `expected_district_version`; when the resolution is a `RESERVE_WITHDRAWAL`, the covenant floor check at adoption time is evaluated against district fields that a prior mutation may already have changed, so a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than allowed to proceed against a district the client has not observed. The guard applies to proposals of every resolution type whenever the field is supplied. Endpoints not named here do not take a version field.

### 2.7. Nested Resource Retrieval and Validation Ordering

The URL hierarchy is district-rooted: every operational path begins with a district id, followed by nested resource ids (member, tap, cycle, invoice, payment, schedule, petition, resolution, order, sample, area). Every district-scoped resource persists that anchoring as a system-maintained `district_id` foreign key on the record itself, set at creation and never editable. Path identifiers are validated left to right — the district id first, then each nested id in path order — and any id that does not exist, or that exists under a different district, yields the corresponding not-found error (`ERR_DISTRICT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_TAP_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_RESOLUTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_AREA_NOT_FOUND`, or `ERR_PAYMENT_NOT_FOUND`), all HTTP 404. A family of reverse-reachability read paths also exists — top-level reads such as a rate schedule, a service area, a member, a tap, a billing cycle, an invoice, or a boil order by bare id, plus nested collection reads hanging off those bare ids — and these follow the same envelope, pagination, and read-permission rules as the district-rooted reads.

When several validations could fire on one request, they are evaluated in a fixed priority order, and the earliest failing check is the one whose error surfaces. Authentication context comes first (missing or malformed headers as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission (`ERR_INSUFFICIENT_PERMISSIONS`). Request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 400 — a required field missing or of the wrong primitive type) is applied after the auth and role checks and before path-existence checks. Path existence (the 404 family) follows. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) is evaluated once the entities it keys on are loaded: on payment collection it follows path existence, because the invoice's cycle must be read to learn which operator billed it, and on record-vote it follows the state-legality and duplicate-vote checks, so a vote that is not recordable at all never reaches the duty check. State-legality checks come next (`ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_READINGS_COMPLETE`, `ERR_CYCLE_NOT_BILLED`, `ERR_MEMBER_NOT_ACTIVE`, `ERR_ORDER_NOT_SAMPLING`, `ERR_PETITION_NOT_REVIEWABLE`, `ERR_RESOLUTION_NOT_PROPOSED`, and the generic invalid-state family), and only then the business-rule checks: boil-order moratorium, notification completeness, sampling window, reading regression and duplication, cycle completeness and window shape, service-area serviceability, rate-schedule sanity, the reserve covenant floor, outstanding-balance and disconnect-eligibility gates on tap actions, tap-fee payment, the one-active-tap rule, the stale-version guard, duplicate votes, the master-reading requirement at close, the no-active-schedule gate, duplicate notifications, the already-reversed guard on payment reversal, and the area-in-use guard on retirement. This ordering matters in practice: a mid-flight boil order surfaces as `ERR_BOIL_ORDER_MORATORIUM` rather than being masked by a later fiscal check, and a stale district version surfaces as `ERR_STALE_VERSION` rather than as a confusingly later business error.

### 2.8. Hierarchical Consistency and Cascade Discipline

Several operations mutate more than one entity, and every cascade is part of the contract. Mutating an entity refreshes its `updated_at` and increments its `version`. District-level events — adopting a rate schedule, billing or closing a cycle, ratifying an annexation, issuing or resolving a boil order, proposing or adopting a board resolution — each increment the district's `version` by 1, which is precisely what the OCC guards in §2.6 observe. Parent-child propagation flows downward as well: disconnecting a tap flips the collection status of its unpaid invoices; recording a compliance-sample result can lift or escalate its parent boil order; a failed annexation ratification cascades the petition back to `REJECTED`. Nothing in this API deletes rows; terminal states (`VOID`, `ABANDONED`, `TERMINATED`, `WITHDRAWN`, `REVERSED`, `SUPERSEDED`, `RETIRED`, `LIFTED`, `VIOLATION_ESCALATED`, `FAILED`, `ADOPTED`, `CLOSED`, `ABSENT`, `PRESENT`, `PAID`-and-`CURRENT`, `RATIFIED`) close lifecycles instead.

## 3. Business Logic & Workflows

### 3.1. Standing Up a District: Areas, Rates, and the Reserve Baseline

A `SystemAdmin` creates a district by supplying its `district_name`, the original `usda_loan_principal_cents` (zero or more), and the `annual_debt_service_cents` (strictly greater than zero). Creation establishes the reserve baseline immediately: `reserve_target_cents` is set equal to `annual_debt_service_cents`, because the USDA covenant requires one full year of debt service on hand; `reserve_balance_cents` starts at 0; and since the balance is below target, `covenant_status` begins as `RESERVE_DEFICIENT`. The district's `current_billing_epoch` starts at 0, `active_rate_schedule_id` is null until the board adopts a first schedule, and `boil_order_active` is false.

Within a district, the `SystemAdmin` also defines certificated service areas, each with an `area_name` and a `boundary_acres` size in whole acres (greater than zero). A new area's `status` is `ACTIVE`. An area may later be retired — `ACTIVE → RETIRED`, or `ANNEXED_IN → RETIRED` for annexed territory — but only when no member references it with a non-terminal `membership_status` (`APPLIED`, `ACTIVE`, or `SUSPENDED`); otherwise the retirement is rejected with `ERR_AREA_IN_USE` (HTTP 409).

Rate schedules are drafted by a `BoardDirector`. A draft carries a `schedule_label`, the monthly `base_minimum_cents` (zero or more) covering the first `included_gallons` (zero or more), the marginal `tier2_rate_cents_per_kgal` for usage above the inclusion up to `tier2_cap_gallons`, the marginal `tier3_rate_cents_per_kgal` for usage beyond that cap, a `tap_fee_schedule` object mapping each member class to its tap fee in cents, and a `reconnect_fee_cents` (zero or more). Draft sanity is checked at creation: `tier2_cap_gallons` must be strictly greater than `included_gallons` and all rates strictly positive, else `ERR_RATE_SCHEDULE_INVALID` (HTTP 422). A new schedule's `status` is `DRAFT`. Adoption happens only through a board resolution (see §3.7): when a `RATE_ADOPTION` resolution is adopted, the target schedule moves `DRAFT → ADOPTED`, any previously `ADOPTED` schedule cascades to `SUPERSEDED`, and the district's `active_rate_schedule_id` is repointed — with the district's `version` incremented. At most one schedule is `ADOPTED` per district at any instant, and new rates apply only to cycles billed after adoption; invoices already issued keep the rate schedule they were pinned to. Adoption repoints the district regardless of the target schedule's prior status: a `DRAFT` target moves to `ADOPTED`, while a target already past `DRAFT` keeps its status and the pointer still moves.

### 3.2. Membership, Taps, and Getting Water to the Meter

Membership begins when a `BillingClerk` files an application with the applicant's `legal_name`, the `service_area_id` of the area containing the parcel, and an optional `member_class` (`RESIDENTIAL`, `COMMERCIAL`, or `AGRICULTURAL`, defaulting to `RESIDENTIAL`). The referenced area must belong to the same district and be in `ACTIVE` or `ANNEXED_IN` status, or the application is rejected with `ERR_AREA_NOT_SERVICEABLE` (HTTP 422). A new member's `membership_status` is `APPLIED`, with `credit_balance_cents` at 0 and `consecutive_delinquent_cycles` at 0. Approval by a `BillingClerk` moves the member `APPLIED → ACTIVE` — the same area-serviceability rule is re-checked at approval, so an application filed against a since-retired area fails with `ERR_AREA_NOT_SERVICEABLE` rather than activating.

Once active, a member can be given a tap. Tap creation by a `BillingClerk` takes the `member_id` and an optional `meter_size` (`FIVE_EIGHTS_INCH`, `THREE_QUARTER_INCH`, `ONE_INCH`, or `TWO_INCH`, defaulting to `FIVE_EIGHTS_INCH`) and quotes `tap_fee_cents` from the district's currently adopted schedule's `tap_fee_schedule` for the member's class (a member class absent from the map quotes 0), with `tap_fee_paid_cents` starting at 0 and status `FEE_PENDING`. Quoting requires an adopted schedule to exist; if the district has none, creation fails with `ERR_NO_ACTIVE_RATE_SCHEDULE` (HTTP 409). A `Treasurer` then collects the tap fee: the tendered `amount_cents` (zero or more) is added to `tap_fee_paid_cents`, which is capped at the quoted fee; any overpayment flows into the member's `credit_balance_cents`, and once the fee is fully covered the tap moves `FEE_PENDING → PAID`. Collection requires the member to be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`, HTTP 409), and collecting on a tap no longer `FEE_PENDING` is rejected with the generic invalid-state error `ERR_INVALID_STATE` (HTTP 409) — and note the segregation of duties here: the clerk creates the tap, the treasurer collects on it.

Meter installation by a `FieldOperator` moves a tap `PAID → INSTALLED`. Installation demands the fee fully paid (attempting it on a `FEE_PENDING` tap surfaces `ERR_TAP_FEE_UNPAID`, HTTP 402), the member still `ACTIVE`, and no other tap of the same member already `INSTALLED` or `RECONNECTED` in the same service area — the one-active-tap-per-member-per-area rule, violated with `ERR_DUPLICATE_ACTIVE_TAP` (HTTP 409). On installation, if a billing cycle is currently `OPEN`, an initial `ACTUAL` meter reading at 0 gallons is auto-created for the tap in that cycle — the most recently opened one if several are `OPEN`. A tap that was never put into service may be abandoned by a `BillingClerk` (`FEE_PENDING` or `PAID → ABANDONED`) only while no invoice exists for it; a tap in one of those two from-states that has any invoice is rejected with `ERR_TAP_HAS_BILLING_HISTORY` (HTTP 409). Abandonment attempted from any other tap status is a state-legality violation under the §2.7 ordering and surfaces the generic invalid-state error `ERR_INVALID_STATE` (HTTP 409) before the billing-history check is reached.

Membership ends by board action: a `BoardDirector` terminates a member (`ACTIVE → TERMINATED`) only when every tap is `ABANDONED` or none exist and no invoice remains in `ISSUED` or `PARTIALLY_PAID` status — otherwise `ERR_OPEN_INVOICES_EXIST` (HTTP 409). Any residual `credit_balance_cents` on termination is forfeited to the district, each forfeiture surfacing as its own positive `ANNUAL_TRUE_UP` reserve entry at the next cycle close.

### 3.3. The Monthly Billing Cycle: Readings, Billing, and Close

A `BillingClerk` opens a billing cycle with `period_start_utc`, `period_end_utc`, and `due_date_utc`. The window must be well-formed: `period_end_utc` strictly after `period_start_utc`, `due_date_utc` at or after `period_end_utc`, and the new cycle's start at or after the previous `CLOSED` cycle's end — no overlap, no back-dating, and cycles still `OPEN`, `READINGS_COMPLETE`, or `BILLED` impose no window constraint — else `ERR_CYCLE_WINDOW_INVALID` (HTTP 422). The new cycle's `cycle_index` is the district's `current_billing_epoch` plus one, strictly increasing per district, and its status is `OPEN`, with `provisional_loss_pct` and `final_loss_pct` null until billing and close respectively compute them.

Field crews then submit meter readings. Each reading names its `tap_id` and `cycle_id`, carries a cumulative `reading_gallons` register value in whole gallons (zero or more), and an optional `reading_type` — `ACTUAL`, `ESTIMATED`, or `FINAL_OFF`, defaulting to `ACTUAL`. Readings are accepted regardless of the cycle's status. The system derives `usage_gallons` as the new register value minus the tap's prior accepted cumulative reading — the tap's most recently accepted reading, whatever cycle it belongs to; a reading below that prior value is a regression, rejected with `ERR_READING_REGRESSION` (HTTP 422). One accepted regular reading per tap per cycle is the rule: once any reading exists for the tap and cycle, another `ACTUAL` or `ESTIMATED` submission is `ERR_DUPLICATE_READING` (HTTP 409). A `FINAL_OFF` reading is the one exception — it may follow the tap's regular reading for the cycle, replacing it at final reconciliation (§3.5) — but a second `FINAL_OFF` for the same tap and cycle is likewise `ERR_DUPLICATE_READING`. Independently, a `FieldOperator` posts the district's master-meter total for the cycle as `master_gallons` (zero or more) against a `cycle_id`; uniqueness is not enforced at posting — several master readings may accumulate for a cycle, and it is cycle close that rejects anything but exactly one.

When every tap in `INSTALLED` or `RECONNECTED` status has an accepted non-`FINAL_OFF` reading for the cycle, the clerk asserts completeness, moving the cycle `OPEN → READINGS_COMPLETE`; if any such tap lacks one, the assertion fails with `ERR_MISSING_METER_READINGS` (HTTP 409). Billing then moves the cycle `READINGS_COMPLETE → BILLED`. Billing requires an adopted rate schedule (`ERR_NO_ACTIVE_RATE_SCHEDULE`, HTTP 409) and does three things at once: it creates one invoice per tap billed in the cycle (see §3.4 for the charge arithmetic), computes the cycle's `provisional_loss_pct` (see §3.5), and applies delinquency aging — every still-unpaid invoice from prior cycles has its collection status advanced per the escalation rules of §3.6 against the logical clock. Billing increments the district's `version`.

Closing the cycle is a `Treasurer` action and is the OCC-guarded write of §2.6: the request carries `expected_district_version`, and a mismatch with the district's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Close requires the cycle to be `BILLED` (`ERR_CYCLE_NOT_BILLED` otherwise) and exactly one `MasterMeterReading` posted for the cycle — zero or two both fail with `ERR_MASTER_READING_REQUIRED` (HTTP 409). Closing computes `final_loss_pct` (§3.5), posts a `MONTHLY_DEPOSIT` reserve entry (§3.8), increments `current_billing_epoch` by 1, walks every member with at least one non-`VOID` invoice billed in this cycle to update `consecutive_delinquent_cycles` — reset to 0 when every such invoice reached `PAID` at a logical-clock instant at or before the cycle's `due_date_utc`, incremented otherwise; members without such an invoice keep their streak unchanged — and increments the district's `version`. The cycle's `billed_total_cents` accumulates the `total_cents` of every non-`VOID` invoice in the cycle.

### 3.4. Charges and Invoices: Minimum-Plus-Tier Arithmetic

Invoices are born at billing time, one per billed tap, from the tap's accepted reading of the cycle — the non-`FINAL_OFF` reading when one exists, otherwise the `FINAL_OFF`. Each invoice carries its `tap_id`; its `member_id` is derived from the tap's owner, its `cycle_id` from the accepted reading, and its `rate_schedule_id` is pinned to the district's `active_rate_schedule_id` at the moment of billing — version-pinned and never re-pinned afterwards, so a later rate adoption does not reach back. The invoice's `usage_gallons` is the billed usage from the accepted reading.

The usage charge is marginal and tiered against the pinned schedule. Let the billed usage be U gallons. The billable quantity above inclusion is U minus `included_gallons`, floored at zero. Of that, the tier-2 quantity is the portion not exceeding `tier2_cap_gallons` minus `included_gallons`; the tier-3 quantity is whatever usage lies above `tier2_cap_gallons` (zero if none). Each tier's gallons are converted to started-thousands by dividing by 1,000 and rounding up to the next whole thousand — a single gallon into a tier bills the full thousand — and the started-thousands multiply the tier's per-thousand rate: tier-2 charge is its started-thousands times `tier2_rate_cents_per_kgal`, tier-3 charge is its started-thousands times `tier3_rate_cents_per_kgal`. The `usage_charge_cents` is the sum of the two tier charges, and the rounding order is pinned: each tier is rounded up before the tiers are summed. `ESTIMATED` readings bill identically to `ACTUAL` ones; when the next cycle's `ACTUAL` reading lands, that cycle's usage is the actual register minus the previously estimated register, which may under- or over-recover against reality and is deliberately not trued-up on the prior invoice.

The invoice total resolves an apparently circular definition with a pinned evaluation order. First the usage charge is computed as above. Then the base is the larger of `base_minimum_cents` alone and `base_minimum_cents` plus the usage charge — in other words the member always pays the monthly minimum plus marginal usage above the inclusion, and the maximum is load-bearing for the zero-usage edge, where it keeps the total at the minimum rather than at minimum-plus-zero being ambiguous. Finally `total_cents` is that base plus `reconnect_fee_cents`, which is non-zero only when the tap carried a pending reconnect fee at billing time (armed at reconnection, §3.6) and is cleared once billed. A disconnected tap still bills the minimum if any reading was accepted for it this cycle; such an invoice carries the reading's `usage_gallons` but a zero `usage_charge_cents` and zero `reconnect_fee_cents`, so its `total_cents` is exactly the pinned schedule's `base_minimum_cents`. The invoice's `minimum_charge_cents` is the pinned schedule's `base_minimum_cents`. Its `billing_status` begins at `ISSUED` and its `collection_status` at `CURRENT` — two parallel dimensions, the first tracking payment posture (`ISSUED → PARTIALLY_PAID → PAID`, or `ISSUED → VOID`), the second tracking collections posture (§3.6). `amount_paid_cents` starts at 0 and `days_past_due` at 0.

### 3.5. Water Loss: Provisional at Bill, Final at Close

The district's conservation obligation is tracked twice per cycle, and the two numbers legitimately diverge.

At billing time, a forward-looking figure is computed. The master side is the most recently posted master reading's `master_gallons` if any has been posted; if none has been posted yet, the master falls back to the sum of sold usage, making the provisional loss provisionally zero. The sold side is the sum of `usage_gallons` over all accepted readings in the cycle, regardless of reading type. The `provisional_loss_pct` is one hundred times the difference of master minus sold, divided by master, rounded half-up to three decimal places — or exactly 0.000 when the master is zero.

At close, the reconciliation is chronological and strict. The master is the cycle's single master reading, which is required. The sold side sums `usage_gallons` over accepted readings processed in chronological order of each reading's `created_at` ascending, ties broken by `reading_gallons` ascending — and a `FINAL_OFF` reading replaces rather than adds to the tap's earlier reading for the cycle, so the tap's sold contribution is its `FINAL_OFF` usage. The `final_loss_pct` is the same hundred-times-difference-over-master formula, three decimals, half-up, with the zero-master case at 0.000. Because a `FINAL_OFF` reading can land between bill and close, the provisional and final percentages are a dual-variant pair on the cycle and need not agree.

### 3.6. Delinquency, Disconnect, and the Path Back

Collection status marches an invoice from `CURRENT` through `DELINQUENT`, `NOTICED`, and `DISCONNECT_ELIGIBLE` to `DISCONNECTED`, with a cure path back to `CURRENT`. Aging is computed in whole days: `days_past_due` is the number of whole days between the logical clock and the cycle's `due_date_utc`, floored at zero while unpaid, frozen at disconnect, and frozen at its current value when the invoice reaches `PAID`; a reversal that un-pays the invoice unfreezes it unless the invoice is `DISCONNECTED`.

Escalation is evaluated at each bill cascade and at explicit notice issuance, and its threshold comparisons are inclusive. Each evaluation advances an invoice at most one rung — a `CURRENT` invoice 50 days past due becomes `DELINQUENT` at that cascade and reaches `NOTICED` only at a later evaluation. When the logical clock has passed `due_date_utc` and the invoice is not yet `PAID`, a `CURRENT` invoice becomes `DELINQUENT`. A `DELINQUENT` invoice whose `days_past_due` has reached at least 10 days becomes `NOTICED` — this happens at a bill cascade, or immediately when a `BillingClerk` issues a disconnect notice on the invoice, which requires the same 10-day threshold and records the notice; issuing a notice on an invoice that is not `DELINQUENT` at ten or more days past due is rejected with the generic invalid-state error `ERR_INVALID_STATE` (HTTP 409). A `NOTICED` invoice at least 45 days past due becomes `DISCONNECT_ELIGIBLE` — a 45-day-old invoice is eligible, the comparison is inclusive.

Physical disconnection is a `FieldOperator` action with two hard gates, and the ordering of §2.7 decides which error surfaces when both could apply. First, the health-safety moratorium: if any boil order is `IN_EFFECT` for the district, no disconnect proceeds, rejected with `ERR_BOIL_ORDER_MORATORIUM` (HTTP 409). Second, every unpaid invoice on the tap must be in `DISCONNECT_ELIGIBLE` status, else `ERR_NOT_DISCONNECT_ELIGIBLE` (HTTP 409). Disconnecting moves the tap `INSTALLED → DISCONNECTED` (or `RECONNECTED → DISCONNECTED`), cascades each unpaid invoice on the tap to collection status `DISCONNECTED` with its `days_past_due` frozen, and — when that was the member's last active tap and any invoice remains unpaid — moves the member `ACTIVE → SUSPENDED`.

The way back runs through payment. Paying an invoice in full always returns its collection status to `CURRENT` from `DELINQUENT`, `NOTICED`, `DISCONNECT_ELIGIBLE`, or `DISCONNECTED`. Reconnection of a `DISCONNECTED` tap by a `FieldOperator` requires every invoice on the tap to be `PAID` — any balance outstanding yields `ERR_OUTSTANDING_BALANCE` (HTTP 402). Reconnection arms a `pending_reconnect_fee` flag on the tap so that the next issued invoice carries `reconnect_fee_cents` from that cycle's pinned schedule (the flag clears once billed), moves the tap to `RECONNECTED`, and restores a `SUSPENDED` member to `ACTIVE`.

### 3.7. Payments, Credits, and Reversals

A `Treasurer` collects against an invoice by tendering `amount_cents` (strictly positive) with the paying `member_id` and target `invoice_id`. Allocation follows a pinned waterfall, and the order matters because reordering changes results when the tender and existing credit each cover portions. Before the new tender is touched, any pre-existing positive `credit_balance_cents` on the member absorbs into the invoice first: the absorb amount is the smaller of the credit balance and the outstanding balance (the invoice's `total_cents` minus `amount_paid_cents`), the credit is drawn down by that amount, and the invoice's applied total grows by it. Then the tender applies: the portion applied is the smaller of `amount_cents` and the remaining outstanding, recorded as the payment's `applied_cents`; any remainder of the tender flows into the member's `credit_balance_cents` as overpayment. The payment's status is `POSTED`. Collection is accepted against an invoice in any billing status — a tender against a fully paid invoice has no outstanding to absorb it and flows entirely into credit — and the paying member need not be the invoice's owner, with all credit effects accruing to the member named in the request.

Payment drives the billing dimension of the invoice. A partial application moves `ISSUED → PARTIALLY_PAID`; covering the full outstanding moves `ISSUED → PAID` or `PARTIALLY_PAID → PAID`, and reaching `PAID` cures collection status back to `CURRENT` regardless of prior state — including from `DISCONNECTED`, which is what re-arms the tap for reconnection eligibility. A posted payment may be reversed by a `Treasurer` as a compensating action: reversal moves the payment `POSTED → REVERSED` (a payment already reversed rejects with `ERR_PAYMENT_ALREADY_REVERSED`, HTTP 409), debits everything that payment applied to the invoice — the tender portion recorded as `applied_cents` plus any credit-absorb amount that grew the invoice's applied total — back off the invoice, debits any overpayment the tender added to the member's `credit_balance_cents` back off the member (the absorbed pre-existing credit is not restored), and recomputes the invoice's billing status from what remains. A reversal does not re-evaluate the invoice's collection status — a cured invoice stays `CURRENT`.

### 3.8. The USDA Reserve Covenant

The reserve fund is a ledger, not a number anyone edits: `reserve_balance_cents` mutates only through `ReserveEntry` rows, each recording its `entry_type` (`MONTHLY_DEPOSIT`, `WITHDRAWAL_AUTH`, or `ANNUAL_TRUE_UP`), a signed `amount_cents` (deposits positive, withdrawals negative), the `cycle_id` it is attributed to (null for withdrawals), and the `resulting_balance_cents` after the entry — a running ledger. At each cycle close, a `MONTHLY_DEPOSIT` entry posts in the amount of one-tenth of one year's debt service per month: the annual debt service divided by 120, rounded up to the next whole cent.

Covenant status derives from the reserve position. The reserve target equals `annual_debt_service_cents` — one full year of debt service — and is recomputed whenever loan terms change. `reserve_deficit_cents` is the shortfall of balance below target, floored at zero. `covenant_status` is `RESERVE_DEFICIENT` when any deficit remains; otherwise `IN_COMPLIANCE`.

Board action can move the reserve in either direction. A `RESERVE_WITHDRAWAL` resolution, on adoption, posts a `WITHDRAWAL_AUTH` entry for the negated `withdrawal_amount_cents` from the resolution's payload — but only if the balance after withdrawal remains at or above 75 percent of the target; a breach is rejected with `ERR_RESERVE_COVENANT_BREACH` (HTTP 409). The floor is evaluated when the deciding vote would adopt the resolution, and a breaching deciding vote is rejected before any vote tally is recorded. Proposing that resolution is the second OCC-guarded write of §2.6 and carries `expected_district_version`. A `LOAN_AMENDMENT` resolution, on adoption, sets `annual_debt_service_cents` to the payload's `new_annual_debt_service_cents`, recomputes the reserve target, and recomputes covenant status. Forfeited member credits surface at cycle close as positive `ANNUAL_TRUE_UP` entries. Covenant status is re-evaluated whenever a reserve entry posts, whenever a loan amendment is adopted, and at every cycle close.

### 3.9. Board Governance: Resolutions and Votes

Board business runs through resolutions. A `BoardDirector` proposes one by naming its `resolution_type` — `RATE_ADOPTION`, `RESERVE_WITHDRAWAL`, `ANNEXATION_RATIFICATION`, or `LOAN_AMENDMENT` — and a polymorphic `subject_id`: a rate schedule for rate adoption, an annexation petition for ratification, the district itself for reserve withdrawal or loan amendment. The `payload` carries type-specific data — `withdrawal_amount_cents` for a withdrawal, `new_annual_debt_service_cents` for a loan amendment, empty otherwise; a withdrawal payload without a non-negative integer `withdrawal_amount_cents`, or a loan-amendment payload without a positive integer `new_annual_debt_service_cents`, is `ERR_INVALID_REQUEST` (HTTP 400). A new resolution is `PROPOSED` with `votes_for` and `votes_against` at 0, and proposing increments the district's `version`.

Voting is one `BoardDirector`, one ballot: each record-vote call carries a `vote` of `FOR` or `AGAINST` and increments the appropriate tally, a director who has already voted on the resolution is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409), and voting on anything not `PROPOSED` yields `ERR_RESOLUTION_NOT_PROPOSED` (HTTP 409). Adoption happens the moment `votes_for` reaches 3 with `votes_for` strictly greater than `votes_against`; failure happens the moment `votes_against` reaches 3 with `votes_against` at least equal to `votes_for`. The segregation-of-duties rule of §2.1 bars the proposer from casting the deciding vote (`ERR_SEGREGATION_OF_DUTIES`). Adoption executes the subject action atomically: rate adoption flips the schedule and repoints the district (§3.1); a reserve withdrawal posts its ledger entry under the covenant floor (§3.8); annexation ratification moves the petition to `RATIFIED` (§3.10); a loan amendment rewrites debt service. Adoption increments the district's `version` — twice when the executed subject action is itself a district-level event under §2.8 (`RATE_ADOPTION` and `ANNEXATION_RATIFICATION`: once for the subject action and once for the adoption) and once otherwise (`RESERVE_WITHDRAWAL`, `LOAN_AMENDMENT`); a failed resolution does not increment it. A failed ratification cascades the petition `APPROVED_PENDING_VOTE → REJECTED`.

### 3.10. Annexation: Petition, Deposit, and the Fee Split

Growth arrives as petitions. A `BillingClerk` files one with the `petitioner_name`, the parcel size `parcel_acres` in whole acres (greater than zero), the `parent_service_area_id` of the existing area the parcel adjoins, and a refundable `deposit_cents` (zero or more). The petition's status is `SUBMITTED`, with `feasibility_fee_cents` and `refund_cents` null until a withdrawal or ratification settles them. A clerk moves it `SUBMITTED → FEASIBILITY_REVIEW`, and a `FieldOperator` recommends it — `FEASIBILITY_REVIEW → APPROVED_PENDING_VOTE` — which requires the parent area to be `ACTIVE` (otherwise the generic invalid-state error `ERR_INVALID_STATE`, HTTP 409). A petition not in the right from-state for one of these actions is rejected with `ERR_PETITION_NOT_REVIEWABLE` (HTTP 409).

Two exits close the review phase, and both settle the deposit the same way. On withdrawal by a clerk — legal only from `FEASIBILITY_REVIEW` — or on ratification by an adopted `ANNEXATION_RATIFICATION` resolution, the deposit splits: the district retains a `feasibility_fee_cents` equal to the larger of 25,000 cents and one-fifth of the cumulative deposit — the percentage leg computed on the full `deposit_cents` including any resubmission top-ups and rounded half-up to integer cents before the maximum is taken — and releases the remainder as `refund_cents`. Ratification additionally creates a new service area named after the petition's `petitioner_name`, with `status` `ANNEXED_IN` and `boundary_acres` equal to the petitioned `parcel_acres`, and increments the district's `version`; adoption settles the deposit and creates the area only while the petition is still `APPROVED_PENDING_VOTE` — a petition that has since moved on leaves the resolution to adopt with no petition effect. Withdrawal simply closes the petition as `WITHDRAWN`. A failed ratification leaves the petition `REJECTED`, from which a clerk may resubmit it back to `SUBMITTED` with a top-up: the request carries `additional_deposit_cents` (zero or more), which is added to `deposit_cents` — so a later fee split computes against the topped-up total.

### 3.11. Boil Orders: Notification, Sampling, and Resolution

When water safety is in doubt, a `FieldOperator` issues a boil order with a regulatory `reason`. Issuance stamps `issued_utc` from the logical clock, computes `notification_deadline_utc` as 24 hours after issuance — every active member must be notified before that instant — sets the district's `boil_order_active` true, and increments the district's `version`. Issuance is not blocked by an existing `IN_EFFECT` order; several may coexist. The order's status is `IN_EFFECT`, and while any order is `IN_EFFECT` the disconnect moratorium of §3.6 applies district-wide.

Notification is documented per member: each receipt names its `boil_order_id` and `member_id` and a `channel` of `DOOR_HANGER`, `CERTIFIED_MAIL`, or `PHONE_TREE`, stamped `notified_utc` from the logical clock. Notifying the same member twice for the same order is rejected with `ERR_DUPLICATE_NOTIFICATION` (HTTP 409), and the order's `notified_member_count` tracks the distinct members notified; receipts may be recorded regardless of the order's status. Sampling may begin — `IN_EFFECT → SAMPLING`, a `FieldOperator` action — only when that count equals the number of district members with `membership_status` `ACTIVE`; otherwise `ERR_NOTIFICATION_INCOMPLETE` (HTTP 409). The district's `boil_order_active` is derived rather than latched: it is true exactly while at least one district order is `IN_EFFECT`, so it clears when the last such order leaves `IN_EFFECT` — including when sampling begins — and sets again when another order is issued.

Samples are collected against the order by a `FieldOperator` naming the `boil_order_id`, a `sample_point` identifier for the distribution tap, and a `collected_utc`. The collection time must not precede the order's `issued_utc` and must fall within 72 hours of it; a violation is `ERR_SAMPLE_WINDOW_VIOLATION` (HTTP 422). Collection is not gated on the order's status. A new sample's `result` is `PENDING`. Recording the result is only legal while the parent order is `SAMPLING` — otherwise `ERR_ORDER_NOT_SAMPLING` (HTTP 409) — and recording a result on a sample that already has one is the generic invalid-state error `ERR_INVALID_STATE` (HTTP 409). A result of `ABSENT` brings the order closer to lifting: when the two most recently resulted samples — in `created_at` order — are both `ABSENT` with no `PRESENT` result anywhere on the order, the order lifts — `SAMPLING → LIFTED` — clearing `boil_order_active` and incrementing the district's `version`. Any single `PRESENT` result escalates instead: `SAMPLING → VIOLATION_ESCALATED`, the district's `version` increments, and a new boil order must be issued before lifting is possible.

## 4. Endpoint Definitions

New resources are created with HTTP 201; modifications and state transitions return HTTP 200. Error responses use the 4xx statuses catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server logical clock to a supplied instant | BillingClerk, Treasurer, BoardDirector, FieldOperator, SystemAdmin |
| POST | /districts | Create a rural water district | SystemAdmin |
| GET | /districts/{id} | Get a district | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts | List districts | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/service-areas | Create a service area | SystemAdmin |
| GET | /districts/{id}/service-areas | List service areas of a district | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/service-areas/{areaId} | Get a service area | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/service-areas/{areaId}/retire | Retire a service area with no live members | SystemAdmin |
| POST | /districts/{id}/members | Apply for membership | BillingClerk |
| GET | /districts/{id}/members | List members | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/members/{memberId} | Get a member | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/members/{memberId}/approve | Approve a membership application | BillingClerk |
| POST | /districts/{id}/members/{memberId}/terminate | Terminate a membership (board action) | BoardDirector |
| POST | /districts/{id}/taps | Create a tap connection, quoting the tap fee from the active schedule | BillingClerk |
| GET | /districts/{id}/taps | List taps | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/taps/{tapId} | Get a tap | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/taps/{tapId}/pay-tap-fee | Collect the tap fee | Treasurer |
| POST | /districts/{id}/taps/{tapId}/install-meter | Install a meter on a paid tap | FieldOperator |
| POST | /districts/{id}/taps/{tapId}/disconnect | Disconnect a tap for non-payment | FieldOperator |
| POST | /districts/{id}/taps/{tapId}/reconnect | Reconnect a disconnected tap after full payment | FieldOperator |
| POST | /districts/{id}/taps/{tapId}/abandon | Abandon a tap with no billing history | BillingClerk |
| POST | /districts/{id}/rate-schedules | Draft a rate schedule | BoardDirector |
| GET | /districts/{id}/rate-schedules | List rate schedules | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/rate-schedules/{scheduleId} | Get a rate schedule | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/billing-cycles | Open a billing cycle | BillingClerk |
| GET | /districts/{id}/billing-cycles | List billing cycles | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/billing-cycles/{cycleId} | Get a billing cycle | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/billing-cycles/{cycleId}/mark-readings-complete | Assert all taps read; cycle moves to readings-complete | BillingClerk |
| POST | /districts/{id}/billing-cycles/{cycleId}/bill | Bill the cycle: invoices, provisional loss, delinquency cascade | BillingClerk |
| POST | /districts/{id}/billing-cycles/{cycleId}/close | Close the cycle: final loss, reserve deposit, epoch increment (OCC-guarded) | Treasurer |
| POST | /districts/{id}/meter-readings | Submit a meter reading for a tap in a cycle | FieldOperator |
| GET | /districts/{id}/meter-readings | List meter readings | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/master-meter-readings | Post the district master-meter total for a cycle | FieldOperator |
| GET | /districts/{id}/master-meter-readings | List master meter readings | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/invoices | List invoices | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /districts/{id}/invoices/{invoiceId} | Get an invoice | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/invoices/{invoiceId}/issue-notice | Issue a disconnect notice on a delinquent invoice | BillingClerk |
| POST | /districts/{id}/payments | Collect a payment against an invoice | Treasurer |
| GET | /districts/{id}/payments | List payments | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/payments/{paymentId}/reverse | Reverse a posted payment | Treasurer |
| GET | /districts/{id}/reserve-entries | List reserve ledger entries | SystemAdmin, BillingClerk, Treasurer, BoardDirector |
| POST | /districts/{id}/board-resolutions | Propose a board resolution | BoardDirector |
| GET | /districts/{id}/board-resolutions | List board resolutions | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/board-resolutions/{resolutionId}/record-vote | Record one board member's vote | BoardDirector |
| POST | /districts/{id}/annexation-petitions | File an annexation petition | BillingClerk |
| GET | /districts/{id}/annexation-petitions | List annexation petitions | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/annexation-petitions/{petitionId}/begin-review | Move a petition to feasibility review | BillingClerk |
| POST | /districts/{id}/annexation-petitions/{petitionId}/recommend | Field recommendation toward a board vote | FieldOperator |
| POST | /districts/{id}/annexation-petitions/{petitionId}/withdraw | Withdraw a petition under review | BillingClerk |
| POST | /districts/{id}/annexation-petitions/{petitionId}/resubmit | Resubmit a rejected petition with a deposit top-up | BillingClerk |
| POST | /districts/{id}/boil-orders | Issue a boil order | FieldOperator |
| GET | /districts/{id}/boil-orders | List boil orders | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/boil-orders/{orderId}/notifications | Record a member notification for a boil order | FieldOperator |
| GET | /districts/{id}/boil-orders/{orderId}/notifications | List notification receipts for an order | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/boil-orders/{orderId}/begin-sampling | Move an order to sampling once all active members are notified | FieldOperator |
| POST | /districts/{id}/compliance-samples | Collect a compliance sample against a boil order | FieldOperator |
| GET | /districts/{id}/compliance-samples | List compliance samples | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| POST | /districts/{id}/compliance-samples/{sampleId}/record-result | Record a sample result | FieldOperator |
| GET | /rate-schedules/{id} | Read a rate schedule by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /service-areas/{id} | Read a service area by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /members/{id} | Read a member by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /taps/{id} | Read a tap by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /billing-cycles/{id} | Read a billing cycle by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /invoices/{id} | Read an invoice by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /boil-orders/{id} | Read a boil order by bare id | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /service-areas/{id}/members | List members of a service area | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /service-areas/{id}/annexation-petitions | List petitions adjoining a service area | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /members/{id}/taps | List a member's taps | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /members/{id}/invoices | List a member's invoices | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /members/{id}/payments | List a member's payments | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /members/{id}/notifications | List a member's notification receipts | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /taps/{id}/meter-readings | List a tap's meter readings | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /taps/{id}/invoices | List a tap's invoices | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /billing-cycles/{id}/meter-readings | List a cycle's meter readings | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /billing-cycles/{id}/master-meter-readings | List a cycle's master meter readings | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /billing-cycles/{id}/invoices | List a cycle's invoices | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /billing-cycles/{id}/reserve-entries | List a cycle's reserve entries | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /invoices/{id}/payments | List an invoice's payments | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /boil-orders/{id}/notifications | List an order's notification receipts | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /boil-orders/{id}/compliance-samples | List an order's compliance samples | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |
| GET | /rate-schedules/{id}/invoices | List invoices pinned to a rate schedule | SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator |

## 5. Error Code Catalogue

Requests to paths this document does not define, or with a method the path does not support, are rejected with `ERR_NOT_FOUND` (HTTP 404 and 405 respectively).

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DISTRICT_NOT_FOUND | 404 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_TAP_NOT_FOUND | 404 |
| ERR_CYCLE_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_SCHEDULE_NOT_FOUND | 404 |
| ERR_PETITION_NOT_FOUND | 404 |
| ERR_RESOLUTION_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_SAMPLE_NOT_FOUND | 404 |
| ERR_AREA_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_CYCLE_NOT_OPEN | 409 |
| ERR_CYCLE_NOT_READINGS_COMPLETE | 409 |
| ERR_CYCLE_NOT_BILLED | 409 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_ORDER_NOT_SAMPLING | 409 |
| ERR_PETITION_NOT_REVIEWABLE | 409 |
| ERR_RESOLUTION_NOT_PROPOSED | 409 |
| ERR_BOIL_ORDER_MORATORIUM | 409 |
| ERR_NOTIFICATION_INCOMPLETE | 409 |
| ERR_SAMPLE_WINDOW_VIOLATION | 422 |
| ERR_READING_REGRESSION | 422 |
| ERR_DUPLICATE_READING | 409 |
| ERR_MISSING_METER_READINGS | 409 |
| ERR_CYCLE_WINDOW_INVALID | 422 |
| ERR_AREA_NOT_SERVICEABLE | 422 |
| ERR_RATE_SCHEDULE_INVALID | 422 |
| ERR_RESERVE_COVENANT_BREACH | 409 |
| ERR_OUTSTANDING_BALANCE | 402 |
| ERR_NOT_DISCONNECT_ELIGIBLE | 409 |
| ERR_TAP_FEE_UNPAID | 402 |
| ERR_DUPLICATE_ACTIVE_TAP | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_MASTER_READING_REQUIRED | 409 |
| ERR_NO_ACTIVE_RATE_SCHEDULE | 409 |
| ERR_DUPLICATE_NOTIFICATION | 409 |
| ERR_TAP_HAS_BILLING_HISTORY | 409 |
| ERR_OPEN_INVOICES_EXIST | 409 |
| ERR_PAYMENT_ALREADY_REVERSED | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_AREA_IN_USE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_NOT_FOUND | 404 |

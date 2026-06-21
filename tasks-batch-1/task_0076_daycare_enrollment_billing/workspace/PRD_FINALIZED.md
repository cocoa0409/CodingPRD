# Daycare Enrollment & Billing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Daycare Enrollment & Billing API, a back-office platform that carries a childcare center from the moment a family joins a waiting list through the day-to-day mechanics of attendance, all the way to monthly invoicing and the annual tax statement parents need at filing time. The system is fundamentally a pricing engine wrapped around a quota: classroom seats are scarce and licensed, so the platform must arbitrate who gets a seat, in what order, and at what price.

Pricing is where the domain earns its complexity. A single child's monthly tuition is the product of several superimposed policies — a center's list price for an age band, an income-driven sliding-scale subsidy that the federal poverty guidelines anchor, and a sibling discount that rewards families enrolling more than one child. These policies do not commute; they must be applied in a fixed order, and a change to any one of them (a new sibling activating, an older sibling graduating, a household income update) ripples across the family's other active enrollments. Layered on top are operational charges that accrue from attendance: late-pickup fines that escalate per block of tardiness, and USDA CACFP meal reimbursements that flow to the center rather than the family.

The API serves four operator and guardian roles working in concert: a center director who runs admissions and the enrollment lifecycle, a billing administrator who owns the financial ledger, parents who act on their own family's children through a check-in app, and teachers who record attendance from the classroom floor. Because several of these actors may touch overlapping resources, the platform relies on optimistic concurrency to keep capacity counts and invoice balances honest under interleaved writes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. The system recognizes exactly four roles, spelled precisely as follows: `CenterDirector`, `BillingAdmin`, `Parent`, and `Teacher`. If either header is missing, or if `X-User-Role` is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of the roles are operator identities not tied to any persisted entity. When `X-User-Role` is `CenterDirector`, `X-User-ID` is an opaque operator identifier; the server does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier with no entity backing. The center director governs admissions, classrooms, family records, the full enrollment lifecycle, and waitlist promotion and expiry; the billing administrator governs invoices, payments, and tax statements.

The other two roles are entity-backed, and this is what binds ownership checks to the header. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare the resource's family linkage to `X-User-ID`. Concretely, a parent may act on a child, a waitlist entry, or an enrollment only when the underlying `Child` belongs to that family, and a violation is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting `Classroom`; ownership checks on any attendance resource compare the classroom of the record's enrollment to `X-User-ID`, and a mismatch is likewise rejected with `ERR_NOT_RESOURCE_OWNER`.

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

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter sets how many leading items are skipped; when omitted it defaults to 0.

Unless an endpoint explicitly states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order. (The one deliberate exception is a classroom's waitlist listing, which is ordered by queue rank as described in §3.) Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. Each such resource has an `id`, a server-minted UUID with no type prefix; a `created_at`, an ISO 8601 UTC timestamp with three fractional digits marking creation; an `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and a `version`, an integer that begins at its initial value and increments by one on every modification. Centers, classrooms, families, sliding-scale rows, children, waitlist entries, enrollments, attendance records, and invoices all carry this full set.

Two resources are deliberately lighter. A `Payment` and a `TaxStatement` are immutable once created: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version` field. They are point-in-time records, never edited after the fact.

Whenever a computed or derived field changes as a side effect of some workflow — a classroom's `active_enrollment_count` and `status`, a family's `account_balance_cents`, an enrollment's `monthly_net_tuition_cents`, an invoice's frozen totals — that change is a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented. State transitions described throughout §3 each increment the transitioning entity's `version` by one.

### 2.5. Nested Resource Retrieval and Existence

Many paths address a resource through one or more parent identifiers. The system validates path identifiers strictly left-to-right: for a request whose path names a center and then a classroom, the center is checked first, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any deeper lookup is attempted. This existence check governs every path-referenced resource — center, classroom, family, child, enrollment, invoice, waitlist entry, and attendance record alike.

Foreign keys carried in a request body are checked separately. When a creation payload references another resource — for example a `classroom_id`, `child_id`, `family_id`, `invoice_id`, or `waitlist_entry_id` — and that reference does not resolve to an existing resource, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This body-reference check applies specifically to the enrollment-creation, waitlist-add, child-registration, attendance-creation, and payment endpoints.

### 2.6. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a request with missing or unknown headers fails with `ERR_UNAUTHENTICATED` before anything else. Role authorization is second, yielding `ERR_FORBIDDEN_ROLE`. Existence of every path-referenced resource is third (`ERR_NOT_FOUND`), followed by existence of every body-referenced foreign key, fourth (`ERR_REFERENCE_NOT_FOUND`). Resource-ownership checks come next — a parent owning the targeted child or a teacher owning the relevant classroom — both surfacing as `ERR_NOT_RESOURCE_OWNER`. Only then are state-machine preconditions evaluated: an operation whose transition is not defined from the resource's current state fails with `ERR_INVALID_STATE`. Business rules specific to each workflow (offer expiry, age-band fit, duplicate guards, capacity, fiscal rules, and so on) follow, each with its own dedicated error described where its workflow lives. Optimistic-concurrency version checks are evaluated late in the chain, yielding `ERR_STALE_VERSION`. Finally, generic request-shape validation — malformed bodies, bad enums, out-of-range numbers — is the lowest-priority catch, surfacing as `ERR_INVALID_REQUEST`. The practical consequence is that, for example, a forbidden role is reported as `ERR_FORBIDDEN_ROLE` even if the body is also malformed, and a missing resource is reported before any state or business rule is consulted.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a parent resource.

The first guards enrollment creation. A create-enrollment request must carry `expected_classroom_version`, a non-optional field holding the client's last observed `version` of the target `Classroom`. If that value does not equal the classroom's current `version` — because another writer has since added an enrollment, advanced the classroom's version, and possibly flipped the classroom to `FULL` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a writer whose view of remaining capacity is stale from consuming a seat it never actually saw available.

The second guards payment application. A create-payment request must carry `expected_invoice_version`, a non-optional field holding the client's last observed `version` of the target `Invoice`. If that value does not equal the invoice's current `version` — because a prior payment that pushed the invoice to `PAID`, or a void, has since advanced the invoice version — the payment is rejected with `ERR_STALE_VERSION` (HTTP 412). This stops a payment built against a superseded invoice view from being applied. No other endpoint takes a version field, and operations not named here perform no version check.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored as integer cents; there are no fractional cents anywhere in the system. Where a calculation divides — applying a percentage share or a discount — the result is rounded half up to the nearest whole cent. The tuition calculation in particular rounds at each step in its pinned sequence rather than rounding only once at the end; the precise mechanics are given in §3 where tuition is derived. Aggregations that sum already-rounded integer components (such as totalling per-enrollment net tuition into an invoice) are exact and require no further rounding.

### 2.9. Capacity and Classroom Status

Each classroom is licensed for a maximum number of simultaneously active enrollments, recorded as its `licensed_capacity`. The classroom tracks how many enrollments are currently in the `ACTIVE` state through its computed `active_enrollment_count`, and exposes a derived `status`: a classroom is `OPEN` while its active count is below its licensed capacity, and `FULL` once the active count reaches the licensed capacity. This `status` is recomputed immediately after every enrollment mutation that changes the active count. Operations that would push a classroom past its licensed capacity are blocked, as detailed in §3.

### 2.10. The Test-Driving Clock

Several rules depend on the current UTC instant — waitlist offer expiry in particular, and all server-minted timestamps. To make these deterministic under test, an administrative capability lets a center director pin the server's notion of "now" to a supplied instant. The capability accepts a single `to_iso8601` value and sets the server's current UTC to that instant for all subsequent timestamp and expiry computations. There is no wall-clock timer anywhere in the system; time-based effects such as offer expiry are realized only through explicit operator sweeps measured against this pinned clock.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Center and Its Classrooms

A center director opens the system by creating a `Center`, supplying its display `name` and its USDA CACFP area-eligibility tier, `cacfp_tier`, which is one of `TIER_I` (the high-reimbursement tier) or `TIER_II` (the low-reimbursement tier). The center also carries three late-pickup policy knobs, each optional at creation and each defaulting if omitted: `late_pickup_grace_minutes`, the number of minutes after a child's scheduled pickup before any fine begins to accrue (default 5, and never negative); `late_pickup_fee_per_block_cents`, the fine charged per started late block (default 1500 cents, never negative); and `late_pickup_block_minutes`, the size of one chargeable late block in minutes (default 15, and at least 1). These three knobs drive the late-fine arithmetic described in §3.6.

Within a center, the director defines classrooms. A `Classroom` is created under a center — its `center_id` ties it to that center — with a `name` such as "Infant A", an `age_band` of `INFANT`, `TODDLER`, or `PRESCHOOL`, a `licensed_capacity` of at least 1, and a `base_monthly_tuition_cents` (the list price for the age band before any subsidy or discount, never negative). A freshly created classroom starts with an `active_enrollment_count` of 0 and a `status` of `OPEN`.

The center director also populates the center's sliding-scale schedule, adding rows that together form the `SlidingScaleTable` for that center. Each row, linked by its `center_id`, names the subsidy `tier` it defines — one of `TIER_A`, `TIER_B`, `TIER_C`, or `FULL_PAY` — an inclusive upper bound `max_fpl_ratio_pct` (the highest income-to-poverty ratio, expressed as a percent, that still falls in this tier; the `FULL_PAY` row uses the sentinel 999999 as its catch-all bound), and a `parent_share_pct` between 0 and 100 giving the percentage of base tuition a family in this tier pays, with the remainder borne by the center as subsidy.

### 3.2. Families, Children, and the Sliding Scale

A `Family` account is created by a center director or billing administrator, anchored to a center through `center_id`, and described by a `primary_contact_name`, the self-reported gross `annual_household_income_cents` (never negative), and a `household_size` of at least 1. On creation the family's `account_balance_cents` is set to 0, and the family's subsidy tier, `sliding_scale_tier`, is computed immediately from the income, the household size, and the center's sliding-scale rows. That tier is one of `TIER_A`, `TIER_B`, `TIER_C`, or `FULL_PAY`.

The sliding-scale tier is derived as follows. First, a household's federal-poverty base is the one-person poverty line of 15,080,000 cents plus 5,320,000 cents for each additional household member beyond the first. The family's poverty ratio, as a percent, is its annual household income multiplied by 100 and divided by that poverty base, with the division floored to a whole percent. The center's sliding-scale rows are then considered in ascending order of their `max_fpl_ratio_pct`, breaking any tie by `created_at` ascending; the first row whose `max_fpl_ratio_pct` is greater than or equal to the family's floored ratio wins, and its `tier` becomes the family's `sliding_scale_tier`. Because the `FULL_PAY` row carries the sentinel bound of 999999, it always serves as the guaranteed catch-all when no lower-bounded tier qualifies.

When a family's circumstances change, a director or billing administrator may update the household figures, supplying a new `annual_household_income_cents`, a new `household_size`, or both. Either change recomputes the family's `sliding_scale_tier` from the same table and increments the family's `version`. The recomputed tier governs future activations; tuition already locked onto active enrollments is not retroactively disturbed (see §3.4).

A `Child` is registered under a family through `family_id`, with a `full_name`, a `birthdate` as an ISO `YYYY-MM-DD` date used to confirm age-band fit at activation, and a flag `enrolls_in_cacfp` indicating whether the family consented to CACFP meal participation for this child (defaulting to true). Each child also carries a `sibling_group_id` that clusters siblings within a family: it points at the eldest enrolled sibling who anchors the cluster, and if it is omitted at registration the system defaults it to the child's own id, making the child its own anchor. A parent may register a child only for their own family; a center director or billing administrator may register on a family's behalf.

### 3.3. The Waiting List

When a desired classroom has no immediate seat, a child is placed on that classroom's waiting list. Adding a child creates a `WaitlistEntry` linking the classroom (`classroom_id`) and the child (`child_id`), entering in the `WAITING` state. A parent, center director, or billing administrator may add a child; a parent may only add their own child. A child may not hold two entries in `WAITING` or `OFFERED` status on the same classroom — a duplicate attempt is rejected with `ERR_DUPLICATE_WAITLIST`.

On entry the system computes two queue attributes. The flag `has_active_sibling` is true when the child shares a `sibling_group_id` with another child who holds an `ACTIVE` enrollment at the same center; this pins the entry's priority class. The integer `priority_rank` then orders the queue, with rank 1 at the front and lower numbers winning: entries whose `has_active_sibling` is true form the leading priority class, and within a single priority class entries are ordered by `created_at` ascending. The entry's own id never breaks ties. A classroom's waitlist listing returns entries in this `priority_rank` order rather than the default creation order.

A center director promotes the front of the queue when a seat is available. Promotion selects exactly one `WAITING` entry deterministically — the entry with the minimum `priority_rank` (sibling-priority class first, then earliest `created_at`) — and moves it from `WAITING` to `OFFERED`. Promotion requires the classroom to be `OPEN` (its active enrollment count below its licensed capacity); if the classroom is already at capacity the promotion is rejected with `ERR_CLASSROOM_FULL`. If there are no `WAITING` entries to choose from, the promotion is rejected with `ERR_WAITLIST_EMPTY`. On a successful promotion the entry's `offer_expires_at` is set to the current UTC instant plus the offer time-to-live of 48 hours, and the entry's `version` is incremented.

An offer that is not converted in time is cleaned up by an operator sweep, never by a background timer. A center director runs the stale-offer sweep on a classroom; it selects every `OFFERED` entry on that classroom whose `offer_expires_at` is earlier than the current UTC instant and moves each from `OFFERED` to `EXPIRED`, incrementing each swept entry's `version`. The sweep applies only to genuinely stale offers — running it against an offer whose expiry has not yet passed is rejected with `ERR_OFFER_EXPIRED`.

A parent may withdraw their own child's waitlist entry at any time while it is `WAITING` or `OFFERED`, moving it to the terminal `WITHDRAWN` state and incrementing its `version`; the parent must own the child or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. The entry's `status` is one of `WAITING`, `OFFERED`, `CONVERTED`, `EXPIRED`, or `WITHDRAWN`, of which `CONVERTED`, `EXPIRED`, and `WITHDRAWN` are terminal.

### 3.4. Enrollment: Offer, Acceptance, and Activation

A center director creates an enrollment, either directly or by converting a promoted waitlist offer. The creation payload names the `child_id` and the `classroom_id`, carries the mandatory `expected_classroom_version` (see §2.7), and may optionally include a `waitlist_entry_id` identifying the promoted offer this enrollment converts; for a direct enrollment that field is left null. The new `Enrollment` begins in the `OFFERED` state, its lifecycle `status` being one of `OFFERED`, `ACCEPTED`, `ACTIVE`, `DECLINED`, `WITHDRAWN`, or `GRADUATED`. Creating the enrollment increments the parent classroom's `version` by one. A child may not hold two non-terminal enrollments at once — that is, two in any of `OFFERED`, `ACCEPTED`, or `ACTIVE` — and an attempt to create a second is rejected with `ERR_DUPLICATE_ENROLLMENT`.

When the create request carries a `waitlist_entry_id`, the named entry must currently be `OFFERED` and its offer must not have lapsed; if the current UTC instant is past that entry's `offer_expires_at`, the conversion is rejected with `ERR_OFFER_EXPIRED`. On a successful conversion the linked waitlist entry transitions from `OFFERED` to `CONVERTED` and its `version` is incremented; the consumed offer is recorded on the enrollment through `waitlist_entry_id`.

The parent who owns the child acts on the offer. Accepting moves the enrollment from `OFFERED` to `ACCEPTED` and increments its `version`. Declining moves it from `OFFERED` to `DECLINED` and increments its `version`; if the enrollment was a converted offer, the linked waitlist entry is left in `CONVERTED` because the offer has already been consumed. Both acceptance and decline require the acting parent to own the child, failing otherwise with `ERR_NOT_RESOURCE_OWNER`.

Activation is the pivotal step, performed by a center director, that moves an enrollment from `ACCEPTED` to `ACTIVE` and freezes its pricing. Activation re-checks capacity at this moment rather than relying on the offer-time view: if the classroom's `active_enrollment_count` has reached its `licensed_capacity`, activation is rejected with `ERR_CLASSROOM_FULL`. The child's `birthdate` must also fit the classroom's `age_band` bounds; a mismatch is rejected with `ERR_AGE_BAND_MISMATCH`. When both gates pass, the enrollment snapshots `locked_base_tuition_cents` from the classroom's current `base_monthly_tuition_cents` so that later list-price edits never retro-bill; the family's `sliding_scale_tier` is recomputed and the matched row's parent share is snapshotted into `locked_parent_share_pct`; the sibling-discount cascade described in §3.5 runs across the family's active siblings; the enrollment's `monthly_net_tuition_cents` is computed; the classroom's `active_enrollment_count` is incremented by one and its `status` recomputed; and the enrollment's `version` is incremented. The starting defaults before activation are a `sibling_discount_pct` of 0, a `locked_base_tuition_cents` of 0, a `locked_parent_share_pct` of 100, and a `monthly_net_tuition_cents` of 0.

A center director may withdraw an `ACTIVE` enrollment, moving it to the terminal `WITHDRAWN` state, or graduate it, moving it to the terminal `GRADUATED` state. Withdrawal carries no precondition beyond the state being `ACTIVE`, and graduation likewise carries no precondition beyond `ACTIVE`. Both decrement the classroom's `active_enrollment_count` by one, recompute the classroom's `status`, run the compensating sibling-discount cascade across the family's remaining active siblings (§3.5), and increment the enrollment's `version`. The terminal enrollment states are `DECLINED`, `WITHDRAWN`, and `GRADUATED`.

### 3.5. Tuition, Subsidy, and the Sibling Discount

The monthly charge for an active enrollment, stored as `monthly_net_tuition_cents`, layers the sliding-scale subsidy and the sibling discount in a strictly pinned order: the sliding scale is applied first, and the sibling discount is applied to that result. Concretely, the post-subsidy amount is the locked base tuition multiplied by the locked parent-share percentage divided by 100, rounded half up to a whole cent. The net tuition is then that post-subsidy amount multiplied by the quantity (100 minus the enrollment's `sibling_discount_pct`) divided by 100, again rounded half up to a whole cent. Rounding happens at each of the two steps; the system does not defer rounding to a single final step.

The sibling discount itself rewards a family for each additional active sibling. Within a family, the active sibling enrollments are ranked by enrollment `created_at` ascending: the earliest-created active enrollment is the anchor and carries a `sibling_discount_pct` of 0, while every junior active sibling carries the sibling discount of 10 percent. The invariant is that a family with at least one active sibling has exactly one anchor at 0 percent.

This ranking is maintained by cascade. When an enrollment activates, the system re-ranks all of the family's active siblings by enrollment creation time, assigns the anchor 0 percent and each junior sibling the 10-percent discount, and recomputes `monthly_net_tuition_cents` for every affected enrollment. When an active sibling withdraws or graduates, the same cascade runs across the family's remaining active siblings — and because the eldest may have departed, a junior sibling can become the new anchor and drop to 0 percent — with each affected enrollment's net tuition recomputed. This compensating recomputation conserves the one-anchor invariant after every departure.

### 3.6. The Check-In App: Attendance, Late Fines, and CACFP

A teacher records a child's arrival through the check-in app, creating an `AttendanceRecord` for one service day. The creation payload names the `enrollment_id`, the `service_date` as an ISO `YYYY-MM-DD` date, and the `scheduled_pickup_local` as an `HH:MM` 24-hour wall-clock time in center-local time, and may include the day's meal counts: `meals_breakfast` (0 or 1), `meals_lunch` (0 or 1), and `meals_snack` (0, 1, or 2), each defaulting to 0. The record is created in the `CHECKED_IN` state with `check_in_at` set to the current UTC instant; `check_out_at` is null until checkout. The acting teacher must own the classroom that the record's enrollment belongs to, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. At most one `CHECKED_IN` attendance record may exist per enrollment per service date; a second is rejected with `ERR_ALREADY_CHECKED_IN`.

Checkout finalizes the day. A teacher checks the child out, which requires that the teacher own the classroom and that `check_out_at` is not already set; on checkout the record moves from `CHECKED_IN` to the terminal `CHECKED_OUT` state, `check_out_at` is set to the current UTC instant, and both the late-fine and CACFP figures are computed and frozen onto the record. The record's `status` is one of `CHECKED_IN` or `CHECKED_OUT`, and its `version` is incremented.

The late-pickup fine works as follows. The scheduled pickup instant is the `service_date` combined with `scheduled_pickup_local`, interpreted in center-local time and converted to UTC. The raw lateness in minutes is the greater of 0 and the number of minutes from that scheduled instant to `check_out_at`. The billable lateness, stored as `late_pickup_minutes`, is the greater of 0 and the raw lateness minus the center's `late_pickup_grace_minutes` — so a child exactly at the grace boundary is billable for 0 minutes and incurs no fine. Each started block counts as a full chargeable unit: when billable lateness is positive, the number of chargeable blocks is the billable minutes divided by the center's `late_pickup_block_minutes`, rounded up to the next whole block (so a single minute past grace already starts and charges one full block); when billable lateness is 0 the block count is 0. The `late_fine_cents` is the number of blocks multiplied by the center's `late_pickup_fee_per_block_cents`. Until checkout occurs late, both `late_pickup_minutes` and `late_fine_cents` remain 0.

The CACFP meal reimbursement accrues to the center, not the family. If the child's `enrolls_in_cacfp` is false, the `cacfp_reimbursement_cents` for the day is 0. Otherwise the center's `cacfp_tier` selects a per-meal rate column, and the reimbursement is the breakfast count times the breakfast rate plus the lunch count times the lunch rate plus the snack count times the snack rate. Under `TIER_I` the per-meal rates are 240 cents for breakfast, 449 cents for lunch, and 119 cents for snack; under `TIER_II` they are 90 cents for breakfast, 271 cents for lunch, and 33 cents for snack — so the same meal counts always yield a strictly smaller reimbursement under `TIER_II` than under `TIER_I`. The result is stored as `cacfp_reimbursement_cents`.

### 3.7. Invoicing and Payment

A billing administrator opens a monthly invoice for a family by creating an `Invoice` for a given `billing_month` (a `YYYY-MM` period); it begins in the `DRAFT` state. The invoice's `status` is one of `DRAFT`, `ISSUED`, `PAID`, or `VOID`, with `PAID` and `VOID` terminal. A draft starts with its computed totals at 0: `tuition_cents`, `late_fines_cents`, `total_cents`, and `amount_paid_cents` all begin at 0, and `issued_at` is unset.

Issuing freezes the totals. A billing administrator issues a draft invoice, moving it from `DRAFT` to `ISSUED`, but only when the family has at least one `ACTIVE` enrollment or at least one late fine in the billing month — an invoice that would have neither is rejected with `ERR_EMPTY_INVOICE`. On issue, `tuition_cents` is frozen as the sum of the family's `ACTIVE` enrollments' `monthly_net_tuition_cents`; `late_fines_cents` is frozen as the sum of `late_fine_cents` across the family's `CHECKED_OUT` attendance records whose `service_date` falls in the billing month; `total_cents` is set to `tuition_cents` plus `late_fines_cents` (an exact sum of already-rounded integer components); `issued_at` is set to the current UTC instant; and the family's `account_balance_cents` is increased by `total_cents` to keep the ledger in sync. The invoice's `version` is incremented.

Payments are applied against an issued invoice by a billing administrator or by the owning parent. A payment names the `invoice_id`, an `amount_cents` of at least 1, a `method` of `CARD`, `ACH`, or `CASH`, and the mandatory `expected_invoice_version` (see §2.7). A payment may not exceed the invoice's outstanding balance — that is, `amount_cents` may not be greater than `total_cents` minus the current `amount_paid_cents` — and an overpayment is rejected with `ERR_OVERPAYMENT`. Applying a payment increases the invoice's `amount_paid_cents` by `amount_cents` and increments the invoice's `version`. When the cumulative `amount_paid_cents` reaches or exceeds `total_cents`, the invoice transitions from `ISSUED` to `PAID` and the family's `account_balance_cents` is decreased by `total_cents`, returning the balance to its pre-issue level for this invoice. A `Payment` is an immutable record carrying its `invoice_id`, `amount_cents`, and `method`.

Voiding reverses an unsettled invoice. A billing administrator may void an invoice from either `DRAFT` or `ISSUED`. Voiding a draft simply moves it to `VOID`. Voiding an `ISSUED` invoice requires that `amount_paid_cents` be exactly 0 — an issued invoice that has already received any payment cannot be voided and is rejected with `ERR_INVOICE_HAS_PAYMENTS` — and on a successful void of an issued invoice the family's `account_balance_cents` is decreased by `total_cents`, compensating the debit recorded at issue time so the balance returns to its pre-issue value. Every void increments the invoice's `version`. A family's `account_balance_cents` thus reflects the sum of `total_cents` over its `ISSUED` invoices net of amounts paid, where a positive balance means money owed.

### 3.8. The Annual Tax Statement

At year's end a billing administrator or the owning parent generates a `TaxStatement` for a family and a given `tax_year` (a calendar year, at least 2000). The statement is computed on a strict cash basis from payments rather than from invoices, so that partial-payment and void cases stay correct. Its `total_paid_cents` is the sum of `amount_cents` across all payments whose invoice belongs to this family, whose invoice is in `PAID` status, and whose invoice `billing_month` falls within the requested tax year. An invoice that was issued but never fully paid — and therefore is not `PAID` — contributes nothing, as does a partially paid still-`ISSUED` invoice.

The statement also reports `child_count`, the distinct number of the family's children who held an `ACTIVE` enrollment at any point during the tax year; an active enrollment whose creation year is at or before the tax year counts the corresponding child. Both fields are computed at generation time and recorded on the immutable statement.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — or add a new distinct resource to a collection — return `201 Created`. Operations that modify an existing resource, including state transitions and sweeps, return `200 OK`. Detailed request and response shapes are reconstructed from the workflow narratives in §3; the table below lists only the HTTP contract and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/centers` | Create a daycare center | CenterDirector |
| GET | `/centers/{id}` | Fetch a center | CenterDirector, BillingAdmin, Parent, Teacher |
| POST | `/centers/{id}/sliding-scale` | Add a sliding-scale tier row to a center | CenterDirector |
| GET | `/centers/{id}/sliding-scale` | List a center's sliding-scale rows | CenterDirector, BillingAdmin |
| POST | `/centers/{id}/classrooms` | Create a classroom under a center | CenterDirector |
| GET | `/centers/{id}/classrooms` | List classrooms under a center | CenterDirector, BillingAdmin, Parent, Teacher |
| GET | `/classrooms/{id}` | Fetch a classroom | CenterDirector, BillingAdmin, Parent, Teacher |
| POST | `/families` | Create a family account | CenterDirector, BillingAdmin |
| GET | `/families` | List families, optionally by center | CenterDirector, BillingAdmin |
| GET | `/families/{id}` | Fetch a family | CenterDirector, BillingAdmin, Parent |
| PATCH | `/families/{id}` | Update household income/size; recompute tier | CenterDirector, BillingAdmin |
| POST | `/children` | Register a child under a family | CenterDirector, BillingAdmin, Parent |
| GET | `/children` | List children, filterable by family | CenterDirector, BillingAdmin, Parent |
| GET | `/children/{id}` | Fetch a child | CenterDirector, BillingAdmin, Parent |
| POST | `/classrooms/{id}/waitlist` | Add a child to a classroom's waitlist | CenterDirector, BillingAdmin, Parent |
| GET | `/classrooms/{id}/waitlist` | List a classroom's waitlist by priority | CenterDirector, BillingAdmin, Parent |
| GET | `/waitlist-entries` | List waitlist entries, filterable by child/classroom | CenterDirector, BillingAdmin, Parent |
| GET | `/waitlist-entries/{id}` | Fetch a waitlist entry | CenterDirector, BillingAdmin, Parent |
| POST | `/classrooms/{id}/waitlist/promote` | Promote the front-of-queue waiting entry | CenterDirector |
| POST | `/classrooms/{id}/waitlist/expire-stale` | Sweep stale offers to expired | CenterDirector |
| POST | `/waitlist-entries/{id}/withdraw` | Parent withdraws their child's waitlist entry | Parent |
| POST | `/enrollments` | Create an enrollment (direct or via offer) | CenterDirector |
| GET | `/enrollments` | List enrollments, filterable by child/classroom | CenterDirector, BillingAdmin, Parent, Teacher |
| GET | `/enrollments/{id}` | Fetch an enrollment | CenterDirector, BillingAdmin, Parent, Teacher |
| POST | `/enrollments/{id}/accept` | Parent accepts an offered enrollment | Parent |
| POST | `/enrollments/{id}/decline` | Parent declines an offered enrollment | Parent |
| POST | `/enrollments/{id}/activate` | Activate an accepted enrollment | CenterDirector |
| POST | `/enrollments/{id}/withdraw` | Withdraw an active enrollment | CenterDirector |
| POST | `/enrollments/{id}/graduate` | Graduate an active enrollment | CenterDirector |
| POST | `/attendance-records` | Teacher checks a child in for a service date | Teacher |
| GET | `/attendance-records` | List attendance records, filterable by enrollment | CenterDirector, BillingAdmin, Teacher, Parent |
| GET | `/attendance-records/{id}` | Fetch an attendance record | CenterDirector, BillingAdmin, Teacher, Parent |
| POST | `/attendance-records/{id}/check-out` | Teacher checks the child out; finalizes fine + CACFP | Teacher |
| POST | `/families/{id}/invoices` | Create a draft invoice for a family + month | BillingAdmin |
| GET | `/families/{id}/invoices` | List a family's invoices | CenterDirector, BillingAdmin, Parent |
| GET | `/invoices/{id}` | Fetch an invoice | CenterDirector, BillingAdmin, Parent |
| POST | `/invoices/{id}/issue` | Freeze totals and issue a draft invoice | BillingAdmin |
| POST | `/invoices/{id}/void` | Void a draft or unpaid issued invoice | BillingAdmin |
| POST | `/payments` | Apply a payment to an issued invoice | BillingAdmin, Parent |
| GET | `/invoices/{id}/payments` | List payments applied to an invoice | CenterDirector, BillingAdmin, Parent |
| POST | `/families/{id}/tax-statements` | Generate a family's annual tax statement | BillingAdmin, Parent |
| GET | `/families/{id}/tax-statements` | List a family's tax statements | CenterDirector, BillingAdmin, Parent |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server's current UTC instant | CenterDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_AGE_BAND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_WAITLIST` | 409 Conflict |
| `ERR_ALREADY_CHECKED_IN` | 409 Conflict |
| `ERR_CLASSROOM_FULL` | 409 Conflict |
| `ERR_WAITLIST_EMPTY` | 409 Conflict |
| `ERR_EMPTY_INVOICE` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

# Custom Tailor & Bespoke Clothing API — Product Requirements Document

## 1. Introduction

A bespoke tailoring house lives and dies by the precision of its promises. A customer who orders a hand-cut suit is committing to weeks of measurement, fabric selection, fitting milestones, and a price that must hold steady even as the catalog underneath it shifts. This API exists to give such a shop a single, authoritative system of record for that entire journey — from the first body scan or tape measurement, through fabric and option selection with a live provisional quote, into the fitting room with its basted, forward, and final milestones, and on to deposit, balance settlement, and the moment the finished garment leaves with its owner.

The system serves four kinds of operator working in concert: the customer who shops and pays for their own work, the sales associate at the front counter who quotes and confirms and takes money, the fitting specialist on the tailoring floor who books the room and the cutter and records how each fitting went, and the shop manager who owns the catalog, the lifecycle exceptions, and the cancellations. Around these people the API enforces the shop's hard commercial rules: a remake policy that compensates the customer in store credit but caps the number of redo attempts, a rush surcharge that raises both the price and the deposit floor, a wedding-and-group ordering flow that discounts by party size and only locks once enough members have committed, and a fabric ledger that reserves yardage off the bolt at confirmation and releases it on cancellation. Pricing is deliberately two-faced: while an order is still a draft it carries a provisional quote that tracks the live catalog, but at confirmation the invoice is frozen against the fabric prices snapshotted when each option line was first added, so the number the customer agreed to is the number they pay. The remainder of this document specifies that contract precisely.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. The system recognizes exactly four roles, spelled precisely as `Customer`, `SalesAssociate`, `FittingSpecialist`, and `ShopManager`. If either header is missing, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). When the headers are well-formed and the role is known, but that role is not permitted to perform the requested operation, the request is rejected instead with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The four roles differ in how their `X-User-ID` relates to persisted data. When `X-User-Role` is `Customer`, the `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer — a `MeasurementProfile`, a `GarmentOrder`, and by extension that order's option lines, payments, and alteration tickets — compare the resource's `customer_id` (directly, or via the owning order) to `X-User-ID`. A customer may act only on their own resources. By contrast, when `X-User-Role` is `SalesAssociate`, `FittingSpecialist`, or `ShopManager`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record or log it, but it does not compare it to any entity's `id`; these three staff roles act across all customers' resources subject only to the operation-level permissions enumerated in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0.

Unless an endpoint says otherwise, every list is ordered by the resource's creation timestamp, `created_at`, in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of matching resources before pagination and `has_more` indicates whether more items remain beyond the current page.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation including those that occur as a side effect of some other operation, and an integer `version` that begins at 1 when the resource is created and increases by exactly 1 on every mutation, including mutations applied as cascaded side effects.

There is one deliberate exception. A `Payment` is an append-only ledger entry: it carries only `id` and `created_at` and does not carry `updated_at` or `version` at all. Its `created_at` doubles as the chronological key by which payments are ordered when balances are computed. Every other resource — `Customer`, `MeasurementProfile`, `Fabric`, `Tailor`, `FittingRoom`, `GarmentOrder`, `GarmentOptionLine`, `Fitting`, `AlterationTicket`, `GroupOrder`, and `Pickup` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Cascades

Many operations in this system touch more than one resource at once. When the server resolves a workflow event — confirming an order, recording a fitting outcome, cancelling an order or a group — it independently mutates each affected resource, refreshing that resource's `updated_at` and incrementing its `version`. A single garment-order cancellation, for example, can ripple into the order's fabric, its payments, its measurement profile, its scheduled fittings, and its enclosing group, and each of those touched resources advances its own `version` as part of the same logical transaction. The order's own `version` likewise advances even when the change to it originated from a cascade rather than a direct write. The detailed cascade rules — what releases, what refunds, what supersedes — live in the workflow narratives of §3; this subsection establishes only that every limb of a cascade is a real mutation with its own `updated_at` and `version` bump.

### 2.6. Nested Resource Retrieval and Path Validation

Several resources are addressed beneath a parent order or group: fittings, option lines, alteration tickets, payments, and pickups each hang under an order — every one of them references its owning order through an `order_id` — and member orders hang under a group. For any request whose path names more than one resource, the server validates each identifier from left to right and rejects on the first that does not resolve. The order identifier is checked before any nested `fittingId`, `ticketId`, or `lineId`; a group identifier is checked before its members. A request against a fitting under a non-existent order therefore fails with `ERR_ORDER_NOT_FOUND` (HTTP 404) before the fitting is ever sought, and only once the order resolves does an unresolvable fitting yield `ERR_FITTING_NOT_FOUND`. Unresolvable nested identifiers surface as `ERR_FITTING_NOT_FOUND`, `ERR_ALTERATION_NOT_FOUND`, or `ERR_GROUP_NOT_FOUND` (all HTTP 404) according to which segment failed. There is no dedicated not-found code for an option-line segment (`lineId`); an unresolvable option line — one whose `id` is unknown or does not belong to the named order — surfaces as `ERR_ORDER_NOT_FOUND` (HTTP 404). Body-level foreign-key references — `customer_id`, `measurement_profile_id`, `fabric_id`, `tailor_id`, `room_id`, and `group_order_id` — are likewise resolved and, if they do not exist, rejected with `ERR_CUSTOMER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`, `ERR_FABRIC_NOT_FOUND`, `ERR_TAILOR_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, or `ERR_GROUP_NOT_FOUND` respectively (all HTTP 404).

### 2.7. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority so that the rejection a caller receives is deterministic. Authentication comes first: the presence and validity of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) is checked before anything else, then the role's permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`). Next the server resolves path resources left to right (the 404 family of §2.6), then body foreign-key references (the not-found family above). After existence comes business referencing and constraint — for an order, that its measurement profile belongs to the same customer (`ERR_PROFILE_CUSTOMER_MISMATCH`, HTTP 422); for a profile, the body-scan reference rule (`ERR_SCAN_REF_REQUIRED`, HTTP 422). Only then does the server evaluate whether the target resource is in a state that permits the requested transition (the state family, HTTP 409) — where a transition does not name its own dedicated state error, this generic check raises `ERR_ORDER_INVALID_STATE` (409); concretely that is the code returned for confirming a non-`DRAFT` order, cancelling an order from a state other than `DRAFT`/`CONFIRMED`/`IN_FITTING`/`REMAKE`, recording a pickup on a non-`READY` order, adding or removing an option line on a non-`DRAFT` order, opening an alteration ticket on an order that is neither `READY` nor `PICKED_UP`, locking a group that is not `FORMING`, and cancelling a group from a state other than `FORMING`/`LOCKED` — followed by the remaining domain-specific constraints — fabric availability, the milestone ladder, tailor and room eligibility, scheduling overlaps, fiscal gating — and finally, on the few guarded writes, the optimistic-concurrency version check (`ERR_STALE_VERSION`, HTTP 412). Malformed request bodies — a missing required field, a wrong type, or an enum value outside the allowed set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Monetary Precision and Rounding

All money in this system is carried in integer cents; there are no fractional-cent amounts stored anywhere. Where a calculation introduces a non-integer intermediate — a tier multiplier, a rush rate, a discount rate — the rounding rule is stated explicitly at the point of calculation in §3, and is one of two forms: "round half up" to a whole cent (the conventional round-to-nearest with halves going up), or "round up" (ceiling) to the next whole cent. The yardage tiers round half up; the rush surcharge, the deposit, and the group discount round up. Because the exact rounding boundary and direction differ between calculations, each §3 formula names its own; none may be substituted for another.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of their parent resource. Scheduling a fitting on an order requires the request to carry `expected_order_version`, holding the `version` of the target `GarmentOrder` that the client last observed; if that value does not equal the order's current `version` at the moment the server processes the request, the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against the order's fitting workflow having already advanced — a prior fitting scheduled, an outcome having cascaded a remake, or the order having been cancelled — since the client read it. Symmetrically, locking a group requires `expected_group_order_version` holding the client's last-observed `GroupOrder.version`, and a mismatch with the group's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412); this guards against the group's membership having changed (a member joining, confirming, or cancelling, each of which recomputes membership and advances the group's version) since the client read it. Cancelling a group is guarded the same way: it too requires `expected_group_order_version` to match the group's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) otherwise. No other endpoint takes a version field, and on the three that do the field is required, not optional.

## 3. Business Logic & Workflows

### 3.1. Customers, Measurement Profiles, and the Catalog

The shop's records begin with the **Customer**. A customer is created with a `full_name` and an `email`; the email is intended to be unique across all customers, but the server does not enforce this at creation — a customer is created from any well-formed `full_name` and `email` (each a required non-empty string) without a duplicate-email check, and no error code is reserved for a duplicate email. Beyond those inputs, every customer carries a set of system-maintained counters that start at known values: `store_credit_cents` begins at 0 and is a non-negative ledger of store credit, credited by remake compensation and by overpaid-balance refunds-to-credit and debited when applied against a balance, never permitted to fall below 0; `remake_count` begins at 0 and counts, over the customer's lifetime, every remake transition across all their orders; `completed_order_count` begins at 0 and counts every one of their orders that reached pickup; and `remake_risk_band` begins at `STANDARD` and is a derived label, one of `STANDARD`, `WATCH`, or `HIGH_RISK`, recomputed whenever the remake count changes (see §3.6).

A **MeasurementProfile** captures one set of body measurements for a customer. It is created against a `customer_id` and records four circumferences and lengths in centimeters — `chest_cm`, `waist_cm`, `hip_cm`, and `inseam_cm` — each of which must be a number strictly greater than 0. The profile's `source` is either `MANUAL` or `BODY_SCAN`, defaulting to `MANUAL` when not supplied. When `source` is `BODY_SCAN`, a `body_scan_ref` (an opaque scan asset reference) is required; when `source` is `MANUAL`, `body_scan_ref` must be absent. A request that supplies a body-scan source without a reference, or a manual source with a reference present, is rejected with `ERR_SCAN_REF_REQUIRED`. A profile's `status` is system-managed and begins at `DRAFT`; it moves to `LOCKED` when it is attached to a confirmed order, and to `SUPERSEDED` when it is replaced or released. Profiles may be listed and filtered by their owning customer.

The **Fabric** catalog is the shop manager's domain. A fabric is created with a `name`, a catalog `price_per_meter_cents` (an integer strictly greater than 0), and an initial bolt quantity supplied at creation as `bolt_meters_initial` (a required number that may not be negative — zero is accepted), which seeds the fabric's running `bolt_meters_remaining`. The remaining meters are debited when an order reserves yardage at confirmation and credited back on cancellation or on a remake release, and never fall below 0. A fabric's `status` is `AVAILABLE` or `DISCONTINUED`, defaulting to `AVAILABLE`; a discontinued fabric cannot be selected on any new option line. The manager may later patch a fabric's `price_per_meter_cents` or `status`, but such an edit changes only the live catalog — it never alters the price already snapshotted onto existing option lines. Each fabric's option-line history can be listed by walking back from the fabric to the lines that selected it.

Two more catalog entities support the fitting room. A **Tailor** is created with a `display_name`, a `skill_tier` of `APPRENTICE`, `JOURNEYMAN`, or `MASTER` (defaulting to `JOURNEYMAN`), and a `status` of `ACTIVE` or `INACTIVE` (defaulting to `ACTIVE`); an inactive tailor cannot be assigned to new fittings, and a final-milestone fitting demands a master, as detailed in §3.3. A **FittingRoom** is created with a `room_name`, a `cleanup_buffer_minutes` value (a non-negative integer defaulting to 15) that the shop enforces as idle time after each booking before the room may be reused, and a `status` of `OPEN` or `CLOSED` (defaulting to `OPEN`); a closed room cannot host new fittings. Both tailors and rooms expose a reverse listing of the fittings booked against them, filterable by `outcome`.

### 3.2. Drafting and Quoting a Garment Order

The central aggregate of the system is the **GarmentOrder**. A draft order is opened against a `customer_id` and a `measurement_profile_id`, with a `garment_type` of `SUIT`, `JACKET`, `TROUSERS`, `SHIRT`, or `DRESS`, a `base_labor_cents` charge (an integer strictly greater than 0), a `fabric_meters_required` quantity (a number strictly greater than 0 that drives both bolt reservation and yardage cost), and a `promised_date` completion target. An order may optionally be marked `is_rush` at draft time (defaulting to false) and may optionally name a `group_order_id` to join a wedding or group order (null for a standalone order). The referenced measurement profile must belong to the same customer named by `customer_id`; if it belongs to a different customer the creation is rejected with `ERR_PROFILE_CUSTOMER_MISMATCH`. A freshly created order has `status` `DRAFT` and a `quoted_total_cents` of 0. If the order joins a group whose `lead_order_id` is still null, this order becomes that group's lead order and the group's member count is recomputed.

To a draft order the shop adds **GarmentOptionLine** entries, each pairing a chosen `fabric_id` with an `option_code`. The referenced fabric must be `AVAILABLE` at the moment the line is created; a line against a discontinued fabric is rejected with `ERR_FABRIC_DISCONTINUED`. The `option_code` is one of `MONOGRAM`, `CONTRAST_LINING`, `WORKING_CUFFS`, `PICK_STITCH`, or `EXTRA_TROUSER`, and each carries a fixed upcharge that is frozen onto the line at creation as `upcharge_cents`: a monogram adds 1500 cents, a contrast lining 4000 cents, working cuffs 6000 cents, pick stitching 3500 cents, and an extra pair of trousers 9000 cents. This upcharge is an exact table lookup recorded once; a later change to the table would never retroactively re-price an existing line. At the same moment the line also snapshots the fabric's then-current catalog price into `fabric_price_per_meter_cents`, so the line remembers the price it was created at even if the fabric is later re-priced. An order's option lines can be listed; a single line on a draft order can be removed, which deletes the line and re-runs the provisional quote, and the removal returns (with HTTP 200) the updated `GarmentOrder` resource — carrying its recomputed `quoted_total_cents` — rather than the deleted line.

While the order remains `DRAFT`, its **provisional quote** — `quoted_total_cents` — is recomputed on every option-line addition or removal. The provisional quote is built from the *live* fabric catalog price, not the per-line snapshot, and proceeds in this order: first the yardage cost is computed from the order's `fabric_meters_required` and the live `price_per_meter_cents` of the fabric, using the tiered yardage rule below; then the option charges are summed across every option line on the order (their order of creation is irrelevant — it is a plain sum of the `upcharge_cents` values); these two figures are added to the order's `base_labor_cents` to form a pre-rush subtotal. If the order is a rush, a rush surcharge equal to the pre-rush subtotal multiplied by thirty percent, rounded up to a whole cent, is added; if the order is not a rush, no surcharge applies. The provisional quote is the pre-rush subtotal plus that rush surcharge.

The **tiered yardage cost** is shared by both the provisional quote and the final invoice, and differs between them only in which price-per-meter it is fed. It applies marginal rates across three meter bands and pins the rounding order: each band's contribution is rounded to a whole cent *independently* and only then are the three rounded contributions summed (round-per-tier-then-sum, never sum-then-round). The first band covers meters above 0 up to and including 3.0 meters, charged at the full price per meter (a multiplier of 1.00). The second band covers the meters above 3.0 up to and including 6.0, charged at ninety percent of the price per meter (a multiplier of 0.90). The third band covers every meter beyond 6.0, charged at eighty percent of the price per meter (a multiplier of 0.80). Concretely, the first band's meters are the lesser of the required meters and 3.0; the second band's meters are the required meters capped at 6.0 minus 3.0, but never less than zero; the third band's meters are the required meters minus 6.0, but never less than zero. Each band's meters are multiplied by the price per meter and by its band multiplier, that product is rounded half up to a whole cent, and the three whole-cent results are added to give the yardage cost.

### 3.3. Confirmation, Fittings, and the Milestone Ladder

A **SalesAssociate** (or a shop manager) confirms a draft order, and confirmation is the moment the price stops moving. Before an order may be confirmed it must satisfy several preconditions: at least one option line must exist on it (otherwise `ERR_NO_OPTION_LINES`, HTTP 409); the linked measurement profile must not be in `SUPERSEDED` status (otherwise `ERR_PROFILE_SUPERSEDED`, HTTP 422); the selected fabric's `bolt_meters_remaining` must be at least the order's `fabric_meters_required` (otherwise `ERR_FABRIC_INSUFFICIENT`, HTTP 409) — the "selected fabric" is the single fabric named on the order's first-created option line (the same line whose snapshot price drives the invoice below), and it is that one fabric whose bolt is checked, reserved, and later released regardless of any other fabrics named on subsequent lines; and if the order belongs to a group, that group must be in `FORMING` status (otherwise `ERR_GROUP_NOT_FORMING`, HTTP 409). When these hold, the order advances from `DRAFT` to `CONFIRMED` and a cascade of side effects fires. The **final invoice** is computed and frozen into `locked_total_cents`; the deposit is computed into `deposit_due_cents`; `balance_due_cents` is set, with nothing yet paid, to the locked total; the fabric's `bolt_meters_remaining` is reduced by the order's `fabric_meters_required` as a reservation; the linked measurement profile moves from `DRAFT` to `LOCKED`; and if the order is in a group, the group's `member_order_count` and `group_total_cents` are recomputed.

The **final invoice** uses the same labor-plus-yardage-plus-options-plus-rush shape as the provisional quote, but with one decisive difference: its yardage cost is computed from a *snapshot* price rather than the live catalog price. The snapshot price used is the `fabric_price_per_meter_cents` recorded on the order's first-created option line — the line with the earliest `created_at`, breaking any tie by `created_at` again and otherwise ignoring `id`. That snapshot price is fed through the tiered yardage rule of §3.2 to produce the yardage component; the option charges are again the sum of every line's `upcharge_cents`; these are added to `base_labor_cents` for a pre-rush subtotal; and, exactly as in the quote, a rush order adds a surcharge of the pre-rush subtotal times thirty percent rounded up, while a non-rush order adds nothing. The result is written to `locked_total_cents` and is never recomputed afterward — so if the catalog price moved between line creation and confirmation, the locked invoice diverges from what a fresh live re-quote would show, and the snapshot wins.

The **deposit** required at confirmation is the locked total multiplied by fifty percent, rounded up to a whole cent. For a rush order this deposit is raised to a floor: it becomes the greater of that computed deposit and 20000 cents. The deposit is written to `deposit_due_cents` within the same confirmation transaction that froze the locked total.

Once confirmed and once the deposit is paid (see §3.4), the order enters the fitting room. A **FittingSpecialist** (or shop manager) schedules a **Fitting**, supplying a `tailor_id`, a `room_id`, a `milestone`, a `start_at`, an `end_at`, and the `expected_order_version` described in §2.9. A fitting may be scheduled while the order is `CONFIRMED`, `IN_FITTING`, or `REMAKE`. Scheduling the first fitting moves the order from `CONFIRMED` to `IN_FITTING` (or, after a remake, from `REMAKE` to `IN_FITTING`), and that first fitting must be at the `BASTED` milestone; a fitting that does not respect the ladder is rejected with `ERR_MILESTONE_OUT_OF_ORDER` (HTTP 409). The very first fitting of round zero may be scheduled only once a `DEPOSIT` payment has been captured summing to at least `deposit_due_cents`; absent that, the transition to fitting is rejected with `ERR_DEPOSIT_NOT_PAID` (HTTP 402). Each successful schedule advances the order's `version` by one — which is precisely why the next scheduler must present a fresh `expected_order_version`.

The fitting **milestone ladder** runs `BASTED`, then `FORWARD`, then `FINAL`, and must be climbed in order within the current remake round: the next milestone that may be scheduled or recorded is the lowest rung not yet passed in this round, and any attempt to skip ahead is rejected with `ERR_MILESTONE_OUT_OF_ORDER`. A fitting carries `start_at` and `end_at`, and `end_at` must be strictly later than `start_at`, otherwise the schedule is rejected with `ERR_INVALID_FITTING_WINDOW` (HTTP 422). The assigned tailor must be `ACTIVE`, or the schedule fails with `ERR_TAILOR_INACTIVE` (HTTP 422); the assigned room must be `OPEN`, or it fails with `ERR_ROOM_CLOSED` (HTTP 422); and a `FINAL`-milestone fitting additionally requires the assigned tailor to be of `MASTER` skill tier, failing otherwise with `ERR_MASTER_TAILOR_REQUIRED` (HTTP 422).

Two scheduling-overlap rules protect the room and the cutter, and they differ deliberately. A fitting occupies its room for its half-open interval from `start_at` up to but not including `end_at`, *plus* the room's `cleanup_buffer_minutes` of trailing buffer afterward; that occupied span must not overlap any other scheduled fitting in the same room, or the booking is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). The tailor's constraint is stricter in inclusivity but has no buffer: a fitting's half-open interval from `start_at` up to but not including `end_at` must not overlap any other scheduled fitting for the same tailor, with no trailing buffer added, and a clash is rejected with `ERR_TAILOR_DOUBLE_BOOKED` (HTTP 409).

### 3.4. Deposits, Balances, and Store Credit

Money moves through an order as a sequence of **Payment** ledger entries, each created with a `kind` of `DEPOSIT` or `BALANCE` and an `amount_cents` strictly greater than 0. Payments are gated by the order's state: a `DEPOSIT` may be captured only while the order is `CONFIRMED`, a `BALANCE` may be captured only while the order is `READY`, and any payment whose amount is not strictly positive is likewise refused — all three conditions, when violated, yield `ERR_PAYMENT_NOT_ALLOWED_NOW` (HTTP 409). A captured payment is recorded with `status` `CAPTURED`; the ledger is append-only, and a payment's `status` becomes `REFUNDED` only through a cancellation refund.

Each capture re-derives the order's settlement figures. The order's `amount_paid_cents` is the sum of the `amount_cents` of its payments whose `status` is `CAPTURED`. The order's `balance_due_cents` is the locked total minus the amount paid minus any store credit already applied (`store_credit_applied_cents`), floored at zero so it can never go negative. To keep that floor honest, balance payments are bounded: a `BALANCE` payment's `amount_cents` may not exceed the current `balance_due_cents` at all — the overpayment tolerance is zero cents — and a balance payment that would exceed the outstanding balance is rejected with `ERR_OVERPAYMENT_REJECTED` (HTTP 422). Capturing a deposit is what makes the order eligible to enter the fitting room, as described in §3.3.

A customer's accumulated store credit can be put toward an order's outstanding balance. Applying credit takes an `amount_cents` that must be an integer of at least 1 (a non-positive or non-integer amount is rejected as a malformed body with `ERR_INVALID_REQUEST`); it debits the customer's `store_credit_cents` and adds the same amount to the order's `store_credit_applied_cents`, after which the balance is recomputed and the updated `GarmentOrder` is returned. The amount applied may not exceed the customer's available `store_credit_cents`, nor may it exceed the order's outstanding `balance_due_cents`; an apply-credit request that breaches either ceiling is rejected with `ERR_INSUFFICIENT_STORE_CREDIT` (HTTP 422). Together the overpayment bound and the apply-credit bound guarantee that the amount paid plus the credit applied never exceeds the locked total, so no surplus ever arises.

### 3.5. Fitting Outcomes, the Remake Cycle, and Readiness

When a fitting concludes, a **FittingSpecialist** (or shop manager) records its outcome by supplying a `result` of `PASS` or `FAIL`, which sets the fitting's `outcome` from `SCHEDULED` to `PASSED` or `FAILED`. An outcome may be recorded only while the parent order is `IN_FITTING`; otherwise the attempt is rejected with `ERR_ORDER_NOT_IN_FITTING` (HTTP 409). A pass is admitted only when every earlier-milestone fitting of the current remake round has already passed; recording a pass out of ladder order is rejected with `ERR_MILESTONE_OUT_OF_ORDER`.

Recording a **pass at the `FINAL` milestone** bubbles the order up from `IN_FITTING` to `READY`, signaling that the garment is made and the order is ready for balance settlement and pickup; readiness is reached only this way — as the automatic side effect of a passing `FINAL` outcome, never through a separate endpoint — so `ERR_FINAL_NOT_REACHED` (HTTP 409), reserved in the catalogue for an attempt to drive an order to readiness without a passing final fitting, is not surfaced by any reachable request. The reciprocal event — recording a **fail at the `FINAL` milestone** — is what opens the remake cycle. If the failing fitting is at `FINAL` and the order's `remake_round` is below the limit of two remakes, the order cascades from `IN_FITTING` to `REMAKE`. A remake cascade does several things at once: it increments `remake_round` by one; it increments the customer's lifetime `remake_count` by one and recomputes their `remake_risk_band` (see §3.6); it grants the customer goodwill store credit by adding the computed remake compensation to `store_credit_cents`; it reserves a fresh cut of fabric by reducing the fabric's `bolt_meters_remaining` by the order's `fabric_meters_required` again; and it closes the round by transitioning every still-`SCHEDULED` fitting on the order to `FAILED`. A non-`FINAL` fitting can never trigger a remake — the cascade requires a final-milestone failure. Recording a `FAIL` at a non-`FINAL` milestone (`BASTED` or `FORWARD`) is nonetheless a valid, successful outcome: it simply sets that fitting's `outcome` to `FAILED` and returns HTTP 200 with the fitting, leaving the order in `IN_FITTING` with no remake cascade and no further side effects. `ERR_REMAKE_REQUIRES_FINAL` (HTTP 409) is reserved in the catalogue for this rule but is not surfaced by any reachable request, since a non-`FINAL` fail is accepted rather than rejected. If a final fitting fails when `remake_round` has already reached the limit of two, no further remake is permitted and the request is rejected with `ERR_REMAKE_LIMIT_REACHED` (HTTP 409).

From `REMAKE`, scheduling a new fitting reopens the workflow: the first fitting of the new round must again be at the `BASTED` milestone, and scheduling it returns the order to `IN_FITTING` at the new remake round. The **remake compensation** granted on each remake is a goodwill credit scaled by the round: it is 5000 cents for the first remake plus an additional 3000 cents for each round beyond the first — concretely, a base of 5000 cents plus 3000 cents times the quantity (remake round minus one), evaluated after `remake_round` has already been incremented, so the first remake yields exactly the 5000-cent base. This raw figure is then capped so the credit never exceeds the order's `locked_total_cents`; the compensation actually granted is the lesser of the scaled figure and the locked total.

### 3.6. Customer Remake Risk

Each time a customer incurs a remake, their **remake risk band** is recomputed from their lifetime remake rate. The rate is the customer's `remake_count` divided by a denominator that is the greater of 1 and the sum of their `completed_order_count` and `remake_count` (the maximum-with-one guards against division by zero before any orders complete). The band is then assigned by comparing that rate against two boundaries, each inclusive: if the rate is at least 0.50 the band is `HIGH_RISK`; otherwise if the rate is at least 0.34 the band is `WATCH`; otherwise the band is `STANDARD`. The resulting band is written to the customer's `remake_risk_band`. This risk lives on the customer and is independent of any single order's cost.

### 3.7. Pickup and Alterations

A garment is released through a **Pickup**. A pickup may be recorded only on an order that is `READY` with a `balance_due_cents` of exactly 0; a pickup attempted while a balance remains outstanding is rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 409). A pickup is also blocked while any alteration ticket on the order remains open, rejected with `ERR_OPEN_ALTERATION_BLOCKS_PICKUP` (HTTP 409). Recording a pickup takes a `released_to_name` for the person collecting the garment and stamps the system-set `picked_up_at` time; it advances the order from `READY` to `PICKED_UP`, increments the customer's `completed_order_count` by one, and — if the order belongs to a group and every non-cancelled member of that group is now `PICKED_UP` — moves the group from `LOCKED` to `FULFILLED`. An order's pickup record can be retrieved as a zero-or-one collection.

After a garment is `READY` or already `PICKED_UP`, the shop can open an **AlterationTicket** against it, carrying a free-text `description` and a `billable_cents` charge (a non-negative integer defaulting to 0, where 0 denotes a courtesy alteration). A ticket's `status` begins at `OPEN`. A **FittingSpecialist** (or shop manager) completes an open ticket, moving it from `OPEN` to `COMPLETED`; if the ticket is billable — its `billable_cents` greater than 0 — completion requires that a `BALANCE` payment summing to at least the billable amount was captured after the ticket was opened, failing otherwise with `ERR_ALTERATION_UNPAID` (HTTP 402). A **ShopManager** may instead void an open ticket, moving it from `OPEN` to `VOIDED`. Either terminal outcome stops the ticket from blocking pickup. Completing or voiding a ticket that is not `OPEN` is rejected with `ERR_ALTERATION_INVALID_STATE` (HTTP 409).

### 3.8. Cancellation and the Release Cascade

A **ShopManager** may cancel an order at any point before it has been picked up — from `DRAFT`, `CONFIRMED`, `IN_FITTING`, or `REMAKE`. The single precondition is that the order has no pickup record; an order that already has a pickup is rejected with `ERR_ALREADY_PICKED_UP` (HTTP 409). Cancellation drives the order to `CANCELLED` and unwinds every commitment the order made. If the order had progressed past draft — that is, it was `CONFIRMED`, `IN_FITTING`, or `REMAKE` — each active fabric reservation it holds is released by crediting the order's `fabric_meters_required` back onto the fabric's `bolt_meters_remaining`, conserving the bolt's meters exactly — the order holds one reservation from confirmation plus one further reservation for each remake round it has entered, so the meters credited back are `fabric_meters_required` multiplied by `(1 + remake_round)`, returned to the first option line's fabric. Every still-`SCHEDULED` fitting on the order is transitioned to `FAILED`. Every `CAPTURED` payment on the order is set to `REFUNDED`, and the sum of those refunded amounts is added to the customer's `store_credit_cents` as a refund-to-credit, conserving the cash-equivalent. The linked measurement profile, if `LOCKED`, is moved to `SUPERSEDED`. And if the order belonged to a group, the group's `member_order_count` and `group_total_cents` are recomputed to reflect the departed member.

### 3.9. Wedding and Group Orders

A **GroupOrder** gathers several garment orders under one wedding or event. It is created with an `event_name` and an `event_date`, starts in `FORMING` status with a `member_order_count` of 0 and a `group_total_cents` of 0, and has a null `lead_order_id` until the first order joins — at which point that first joining order becomes the designated lead order, whose customer is treated as the group organizer. The group's `member_order_count` is the count of non-cancelled garment orders whose `group_order_id` names this group. Members may be listed by walking from the group to its orders, and groups themselves may be listed and filtered by their `lead_order_id`.

The group's running `group_total_cents` is recomputed whenever a member order confirms or cancels and again when the group is locked. It is built by first summing, then discounting, in that pinned order. The members that count toward the total are the garment orders in this group whose status is `CONFIRMED`, `IN_FITTING`, `REMAKE`, `READY`, or `PICKED_UP`; their `locked_total_cents` are summed into a raw sum. A member-count discount tier is then chosen from the number of such members: if there are at least 8 members the discount rate is ten percent; otherwise if there are at least 4 members the discount rate is five percent; otherwise there is no discount. The group total is the raw sum minus the discount, where the discount is the raw sum multiplied by the chosen rate and rounded up to a whole cent — the sum is formed first and only then is the rounded discount subtracted from it.

A **ShopManager** locks a forming group once it is large enough, supplying the `expected_group_order_version` for the OCC check of §2.9. Locking requires that `member_order_count` — the count of non-cancelled member orders — is at least the minimum of three members (otherwise `ERR_GROUP_TOO_SMALL`, HTTP 409) and that the group still has at least three members that have advanced past draft — that is, at least three members in `CONFIRMED`, `IN_FITTING`, `REMAKE`, `READY`, or `PICKED_UP` (otherwise `ERR_GROUP_HAS_DRAFT_MEMBERS`, HTTP 409). A still-`DRAFT` non-cancelled member does not by itself block the lock so long as three or more qualifying members remain; it is simply excluded from the locked-in set rather than rejecting the lock. A successful lock moves the group from `FORMING` to `LOCKED`, sets `member_order_count` to the non-cancelled member count, recomputes `group_total_cents` over the locked-in (qualifying-state) member set, and advances the group's `version`. A locked group reaches `FULFILLED` automatically when its last non-cancelled member order is picked up — fulfillment is only ever this automatic side effect of a member pickup (it requires the group to be `LOCKED` with at least one non-cancelled member, all of whose non-cancelled members are now `PICKED_UP`), never a separately callable transition, so `ERR_GROUP_MEMBERS_PENDING` (HTTP 409), reserved for a fulfillment attempted while some non-cancelled member is not yet `PICKED_UP`, is not surfaced by any reachable request. A shop manager may also cancel a group from either `FORMING` or `LOCKED`, again supplying `expected_group_order_version`; cancelling drives the group to `CANCELLED`, advances its `version`, and cascade-cancels each of its non-terminal member orders — those in `DRAFT`, `CONFIRMED`, `IN_FITTING`, `REMAKE`, or `READY` — through the same order-cancellation release cascade described in §3.8.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify, transition, or read an existing resource — including lifecycle transitions such as confirm, lock, and cancel — return a `200 OK` status code. (Recording a pickup creates a new Pickup resource and therefore returns `201`.) The request body, response body, and side effects of each endpoint are specified in the §3 narratives; the table below gives only the routing surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | ShopManager, SalesAssociate |
| GET | `/customers/{id}` | Get a customer | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| GET | `/customers` | List customers | ShopManager, SalesAssociate |
| POST | `/measurement-profiles` | Create a measurement profile | ShopManager, SalesAssociate, Customer |
| GET | `/measurement-profiles/{id}` | Get a measurement profile | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| GET | `/measurement-profiles` | List measurement profiles | ShopManager, SalesAssociate, Customer |
| POST | `/fabrics` | Create a fabric catalog entry | ShopManager |
| GET | `/fabrics/{id}` | Get a fabric | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| GET | `/fabrics` | List fabrics | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| PATCH | `/fabrics/{id}` | Update fabric price or status | ShopManager |
| GET | `/fabrics/{id}/option-lines` | List option lines that selected this fabric | ShopManager, SalesAssociate |
| POST | `/tailors` | Create a tailor | ShopManager |
| GET | `/tailors/{id}` | Get a tailor | ShopManager, SalesAssociate, FittingSpecialist |
| GET | `/tailors` | List tailors | ShopManager, SalesAssociate, FittingSpecialist |
| GET | `/tailors/{id}/fittings` | List a tailor's fittings | ShopManager, SalesAssociate, FittingSpecialist |
| POST | `/fitting-rooms` | Create a fitting room | ShopManager |
| GET | `/fitting-rooms/{id}` | Get a fitting room | ShopManager, SalesAssociate, FittingSpecialist |
| GET | `/fitting-rooms` | List fitting rooms | ShopManager, SalesAssociate, FittingSpecialist |
| GET | `/fitting-rooms/{id}/fittings` | List a room's fittings | ShopManager, SalesAssociate, FittingSpecialist |
| POST | `/group-orders` | Create a group order container | ShopManager, SalesAssociate |
| GET | `/group-orders/{id}` | Get a group order | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| GET | `/group-orders` | List group orders | ShopManager, SalesAssociate |
| GET | `/group-orders/{id}/orders` | List member orders of a group | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| POST | `/group-orders/{id}/lock` | Lock a forming group | ShopManager |
| POST | `/group-orders/{id}/cancel` | Cancel a group and cascade-cancel its members | ShopManager |
| POST | `/orders` | Create a draft garment order | ShopManager, SalesAssociate, Customer |
| GET | `/orders/{id}` | Get a garment order | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| GET | `/orders` | List garment orders | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| POST | `/orders/{id}/confirm` | Confirm a draft order | SalesAssociate, ShopManager |
| POST | `/orders/{id}/cancel` | Cancel an order and run the release cascade | ShopManager |
| POST | `/orders/{id}/pickup` | Record garment pickup on a settled order | SalesAssociate, ShopManager |
| GET | `/orders/{id}/pickup` | Get the pickup record of an order | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| POST | `/orders/{id}/option-lines` | Add an option line to a draft order | SalesAssociate, ShopManager, Customer |
| GET | `/orders/{id}/option-lines` | List an order's option lines | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| DELETE | `/orders/{id}/option-lines/{lineId}` | Remove an option line from a draft order | SalesAssociate, ShopManager, Customer |
| POST | `/orders/{id}/fittings` | Schedule a fitting (OCC-guarded) | FittingSpecialist, ShopManager |
| GET | `/orders/{id}/fittings` | List an order's fittings | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| POST | `/orders/{id}/fittings/{fittingId}/record-outcome` | Record a fitting PASS/FAIL | FittingSpecialist, ShopManager |
| POST | `/orders/{id}/alterations` | Open an alteration ticket | SalesAssociate, FittingSpecialist, ShopManager, Customer |
| GET | `/orders/{id}/alterations` | List an order's alteration tickets | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| POST | `/orders/{id}/alterations/{ticketId}/complete` | Complete an alteration ticket | FittingSpecialist, ShopManager |
| POST | `/orders/{id}/alterations/{ticketId}/void` | Void an alteration ticket | ShopManager |
| POST | `/orders/{id}/payments` | Capture a deposit or balance payment | SalesAssociate, ShopManager, Customer |
| GET | `/orders/{id}/payments` | List an order's payments | ShopManager, SalesAssociate, FittingSpecialist, Customer |
| POST | `/orders/{id}/apply-credit` | Apply store credit against an order's balance | SalesAssociate, ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_FITTING_WINDOW` | 422 Unprocessable Entity |
| `ERR_SCAN_REF_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_FABRIC_NOT_FOUND` | 404 Not Found |
| `ERR_TAILOR_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_FITTING_NOT_FOUND` | 404 Not Found |
| `ERR_ALTERATION_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_PROFILE_CUSTOMER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PROFILE_SUPERSEDED` | 422 Unprocessable Entity |
| `ERR_FABRIC_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_NO_OPTION_LINES` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_IN_FITTING` | 409 Conflict |
| `ERR_ALREADY_PICKED_UP` | 409 Conflict |
| `ERR_MILESTONE_OUT_OF_ORDER` | 409 Conflict |
| `ERR_MASTER_TAILOR_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TAILOR_INACTIVE` | 422 Unprocessable Entity |
| `ERR_ROOM_CLOSED` | 422 Unprocessable Entity |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_TAILOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_FINAL_NOT_REACHED` | 409 Conflict |
| `ERR_REMAKE_REQUIRES_FINAL` | 409 Conflict |
| `ERR_REMAKE_LIMIT_REACHED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 402 Payment Required |
| `ERR_PAYMENT_NOT_ALLOWED_NOW` | 409 Conflict |
| `ERR_OVERPAYMENT_REJECTED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 422 Unprocessable Entity |
| `ERR_FABRIC_INSUFFICIENT` | 409 Conflict |
| `ERR_BALANCE_OUTSTANDING` | 409 Conflict |
| `ERR_OPEN_ALTERATION_BLOCKS_PICKUP` | 409 Conflict |
| `ERR_ALTERATION_UNPAID` | 402 Payment Required |
| `ERR_ALTERATION_INVALID_STATE` | 409 Conflict |
| `ERR_GROUP_NOT_FORMING` | 409 Conflict |
| `ERR_GROUP_TOO_SMALL` | 409 Conflict |
| `ERR_GROUP_HAS_DRAFT_MEMBERS` | 409 Conflict |
| `ERR_GROUP_MEMBERS_PENDING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

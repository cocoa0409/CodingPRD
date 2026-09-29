# DMC Ground Operations API — Product Requirements Document

## 1. Introduction

A destination management company sells one thing: the certainty that a group of several hundred visitors will be met at the airport, moved, fed, entertained and flown home without anyone noticing the machinery underneath. That machinery is currently held together by spreadsheets. Programme designers keep the venue grid in one workbook, the contracting desk keeps deposit schedules and certificates of insurance in another, permit officers track municipal street-closure applications by email, and the on-site coordinators reconcile actual attendance against guaranteed counts on paper the morning after the farewell dinner. Every hand-off is an opportunity for the same head count to be billed twice, for an uninsured coach operator to appear at a hotel kerb, or for a greeter whose airport badge expired on Tuesday to be standing in arrivals on Wednesday.

This document specifies the DMC Ground Operations API — a single system of record spanning programme design, local supplier assembly, transportation and manifest management, staffing with credentialing, permitting, on-site execution, post-programme reconciliation and, finally, client billing with disclosed markup and supplier settlement. The API is mounted under the `/dmc` prefix, with one auxiliary test-driving surface described in §2.4.

Two design commitments shape everything that follows. First, a programme's operational life and its financial life advance on **two independent tracks**: what happened on the ground and what is owed for it are tracked separately, so a programme can be operationally finished while its money is still moving, and a client invoice can be credited and re-cut without anybody re-delivering a gala dinner. Second, **money is conserved and markup is disclosed**. The client is contractually entitled to see the supplier subtotal, the disclosed markup and the tiered management fee as three separate figures, and the sum that the DMC owes its suppliers must at every instant equal the sum it has settled plus the sum it still has open. Both commitments are enforced by the API rather than trusted to operator discipline.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, empty or malformed, or if `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the declared role is not among those authorised for the endpoint being called (see the authorisation column of §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The six roles, spelled exactly as the API expects them, are `ProgramDirector`, `OperationsCoordinator`, `SupplierManager`, `Supplier`, `Controller` and `PermitOfficer`.

- A `ProgramDirector` owns programme design: creating programmes, curating the element set, registering venues and staff members, proposing, confirming and releasing shifts, opening reconciliation, and editing or approving reconciliation lines. They cannot touch the vendor file, permits or money movement.
- An `OperationsCoordinator` runs the ground operation: scheduling transport, managing manifests, marking elements ready, delivering them, switching to weather alternatives, departing vehicles and checking staff in.
- A `SupplierManager` owns the vendor file and the contracting cycle: onboarding suppliers, maintaining certificates of insurance, and drafting, sending, countersigning and terminating contracts. They cannot design programmes or move money.
- A `Supplier` is an external local vendor. It sees contract reads and may counter a contract addressed to its own supplier record; every other write is denied.
- A `Controller` owns client billing and supplier settlement: issuing and crediting invoices, opening settlements, approving them and releasing funds.
- A `PermitOfficer` handles street-closure, special-venue and off-premise permitting with the issuing authorities, and owns the whole permit lifecycle and nothing else.

Identity semantics differ by role, and they matter because two operations compare `X-User-ID` against a stored foreign key rather than against a role name.

- When `X-User-Role` is `OperationsCoordinator`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID`. Concretely, an on-site staff check-in requires that `X-User-ID` equal the assignment's `staff_id`, so that presence on site is attributable to a real person; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's foreign-key field to `X-User-ID`. A counter-offer on a contract therefore requires `X-User-ID` to equal that contract's `supplier_id`, and a supplier attempting to counter somebody else's contract receives `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `ProgramDirector`, `SupplierManager`, `Controller` or `PermitOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `sent_by_user_id` and `countersigned_by_user_id` on a supplier contract, and as `approved_by_user_id` and `released_by_user_id` on a settlement payment, where the corresponding transitions write it — but it never compares it to any entity's `id`. Those recorded identifiers exist so the segregation-of-duties rules of §2.10 can compare one operator against another.

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

### 2.3. Pagination and List Filtering

List endpoints are paginated through two query parameters. `limit` sets the maximum number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` sets the number of rows to skip and defaults to 0. A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint says otherwise, list results are sorted by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count` and `has_more`.

Beyond pagination, list endpoints accept domain filters, all of them optional and all of them exact-match. Programmes may be filtered by `execution_status` and `settlement_status`. Venues, supplier contracts, program elements, permits, transport segments, manifest entries, staff assignments, reconciliation lines and settlement payments each accept `status`. Suppliers accept `supplier_type` and `status`; staff members accept `role_type`, `status` and the derived `credential_status`. Relationship filters are available where the workflow needs them: `program_id` on supplier contracts, program elements, transport segments, staff assignments, reconciliation lines and settlement payments; `supplier_id` on supplier contracts, program elements, reconciliation lines and settlement payments; `contract_id` on settlement payments; `venue_id`, `predecessor_element_id` and `alternative_for_element_id` on program elements; `element_id` on permits, program elements' own children, staff assignments and reconciliation lines; `segment_id` on manifest entries and staff assignments; and `staff_id` on staff assignments.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource in this system — programmes, venues, suppliers, supplier contracts, program elements, permits, transport segments, manifest entries, staff members, staff assignments, reconciliation lines and settlement payments — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations that only touch derived figures.
- `version` (integer): a counter that increments by exactly one on every mutation of the row. No entity in this system is exempt from `updated_at` or `version`.

Both `created_at` and `updated_at` are read from the logical clock described just below rather than from real time, so every row written or touched while the clock is held at one instant carries that instant; the envelope's `api_request_timestamp` is the one timestamp in this system taken from real time. Because rows can therefore share a `created_at`, wherever `created_at` orders rows or breaks a tie between them, two rows sharing it are ranked by the sequence in which they were created, the row created later counting as the later of the two.

A temporal field that arrives in a request body is handled differently from these server-managed stamps: it is stored as the literal the client filed, with surrounding whitespace trimmed, and read back verbatim rather than re-rendered. A programme's `arrival_date` and `departure_date`, a supplier's `insurance_expires_on`, a program element's or a staff assignment's `starts_at` and `ends_at`, a transport segment's `depart_at` and `arrive_at`, and a staff member's `badge_expires_on` and `first_aid_expires_on` all behave this way, so an `arrival_date` supplied as `"2026-09-10"` reads back as `"2026-09-10"` while one supplied as `"2026-09-10T08:30:00Z"` reads back as `"2026-09-10T08:30:00Z"`. Any such literal is nevertheless interpreted as an instant for every comparison the rules below make: a value carrying no zone designator is read as UTC, and unless a rule says otherwise a bare `YYYY-MM-DD` date is read as the midnight instant that begins that day.

Because a great many rules in this domain are deadlines — insurance expiry, credential expiry, permit lead time, check-in windows, departure due times, cancellation-penalty tiers — the server does **not** read wall-clock time. It reads a **logical clock** whose value is explicit and settable. On start-up the logical clock reads exactly `2026-08-01T00:00:00Z`, and it holds that value until it is moved. An operator of any of the five internal roles (`ProgramDirector`, `OperationsCoordinator`, `SupplierManager`, `Controller`, `PermitOfficer`) may move it by supplying a `to_iso8601` instant to the test-driving clock capability described in §4; the response echoes the resulting `current_utc`, rendered in the canonical ISO 8601 UTC form with three fractional digits whatever literal was supplied. Advancing or rewinding the clock immediately changes every derived credential status, every cancellation-penalty tier, every permit lead-time computation and every check-in window, because those rules are evaluated at read time or at transition time against the clock's current value.

### 2.5. Optimistic Concurrency on Parent Aggregates

Two creation operations write a child row whose contents are derived from a parent aggregate's current shape, and both are guarded by optimistic concurrency against that parent.

Creating a program element requires a non-optional `expected_program_version` field carrying the client's last observed `version` of the parent programme named by `program_id`. If that value does not equal the programme's current `version`, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). The guard exists because a new element legitimately supersedes the programme's design snapshot — it changes `element_count`, `open_element_count` and therefore the estimate basis — so a writer holding a stale view of the programme must re-read it before adding to the design.

Creating a settlement payment requires a non-optional `expected_contract_version` field carrying the client's last observed `version` of the supplier contract named by `contract_id`. If that value does not equal the contract's current `version`, the create is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The payment's gross and deposit-applied figures are derived from the contract's `deposit_paid_cents` and `status` at creation time, so a writer holding a stale contract view would otherwise settle against superseded deposit terms.

No other endpoint accepts a version field, and no other endpoint performs a version comparison. Endpoints not named in this subsection are not guarded by optimistic concurrency at all.

### 2.6. Money, Head Counts and Rounding Discipline

All monetary amounts in this system are integers denominated in cents; every field name ending in `_cents` is an integer count of cents, never a decimal currency figure. Percentages and ratios — `markup_pct`, `deposit_pct`, `variance_pct`, `fee_pct_applied` — are plain numbers.

Wherever a monetary result must be derived from a percentage or a per-minute rate, the result is rounded **half up** to a whole number of cents. Three rounding-order rules are normative and must not be simplified:

1. **Markup is rounded per reconciliation line and only then summed.** Rounding each line's markup separately and adding the rounded results gives a different total from summing the raw supplier costs first and rounding once; the per-line order is the correct one.
2. **The two legs of a labour cost are rounded separately and only then added.** The regular-time leg is rounded half up to cents, the overtime leg is rounded half up to cents, and the two rounded figures are summed.
3. **The deposit waterfall does no rounding at all.** It only redistributes existing integer cent amounts, so the deposit applied plus the deposit left over always equals the contract's recorded paid deposit exactly.

Head counts are integers. The only place a fractional head count arises is the supplier attrition floor, and there the figure is rounded **up** to the next whole guest (§3.8). The variance ratio on a reconciliation line is kept to four decimal places, rounded half up.

### 2.7. Cascade Depth, Derived Counters and Bubble-Up States

Most interesting transitions in this domain touch more than one row. The API applies every consequence of a transition inside the same request, in the order the workflow narrative in §3 describes, and each touched row has its own `updated_at` refreshed and its own `version` incremented by one. Three properties of these cascades are worth stating once, globally.

**Cascades are transitive, not one level deep.** A permit denial blocks the element it authorised; blocking the element releases that element's proposed and confirmed shifts; each released shift decrements its staff member's confirmed-minutes accumulator and increments the programme's staffing-gap counter. That is a four-level chain driven by a single request, and every level must actually fire.

**Some counters are monotonic and some are recomputed.** `staffing_gap_count` on a programme is a monotonic incident counter: it rises by one every time a staff assignment leaves `CONFIRMED` for `RELEASED` or `NO_SHOW`, and it is never decremented, because a gap that had to be back-filled remains a recorded fact of how the programme ran. `unseated_guest_count` behaves the same way for guests displaced by a segment cancellation. By contrast `element_count`, `open_element_count`, `actual_attendance_total`, `booked_seat_count`, `seated_guest_count`, `confirmed_minutes_total` and every `_cents` aggregate are **recomputed** from their contributing rows whenever a contributing row changes.

**Parent states can be derived from children.** A programme's operational completion is not requested by anybody: it is inferred. Whenever a program element finishes — by delivery, by weather substitution or by cancellation — the server re-evaluates the parent, and if the programme is `IN_EXECUTION` and no open element remains, the programme itself advances to `COMPLETED`. The settlement dimension has the mirror-image behaviour: a programme reaches `SETTLED` not by request but because a settlement payment was released while nothing remained open on the supplier side.

### 2.8. Path Resolution and Reference Checking

Endpoint paths in this API are flat: each write or read addresses one resource by one identifier. Where an identifier appears in the path, it is resolved before any body field is examined, and where several appear they are resolved strictly left to right, so the first unresolvable identifier determines the error. Each resource type has its own not-found code, all of them HTTP 404: `ERR_PROGRAM_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ELEMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_MANIFEST_ENTRY_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, `ERR_RECONCILIATION_LINE_NOT_FOUND` and `ERR_SETTLEMENT_PAYMENT_NOT_FOUND`.

Foreign keys supplied in a request body are resolved next, in the order the endpoint's input list declares them, and they raise the same family of 404 codes. A `program_id`, `supplier_id`, `venue_id`, `contract_id`, `element_id`, `predecessor_element_id`, `alternative_for_element_id`, `segment_id`, `target_segment_id` or `staff_id` that names no row is a 404, not a 400. Body-level reference resolution applies when drafting a supplier contract, adding a program element, opening a permit, scheduling a transport segment, manifesting a guest, proposing a staff assignment, opening a settlement payment, and moving a manifest entry to another segment.

### 2.9. Order of Rejection

Many operations in this system are guarded by half a dozen checks at once, and which error a client sees is part of the contract. Checks are evaluated in the following fixed order, and the **first** failing check determines the response; later checks are not evaluated.

1. Authentication of the two headers — `ERR_UNAUTHENTICATED`.
2. Role authorisation for the endpoint — `ERR_ROLE_NOT_PERMITTED`.
3. Existence of every path identifier, left to right — the twelve not-found codes.
4. Existence of every foreign key in the body, in declared field order — the same not-found codes.
5. Ownership, for the two identity-bound operations — `ERR_NOT_RESOURCE_OWNER`.
6. Request shape: required fields present, enum members legal, integers at or above their declared minima, datetime pairs strictly ordered, pagination in range — `ERR_INVALID_REQUEST`.
7. Optimistic concurrency on the parent aggregate — `ERR_STALE_PROGRAM_VERSION` or `ERR_STALE_CONTRACT_VERSION`.
8. Transition legality: the target row's current status must be a declared source state of the requested transition. Every second application of a one-shot trigger fails here with `ERR_INVALID_STATE_TRANSITION`. A `PATCH` requests no transition, so where a `PATCH` nevertheless requires a particular source status that requirement is evaluated after the programme phase and window bands below rather than here.
9. Design-lock protection on element-set mutations — `ERR_PROGRAM_DESIGN_LOCKED`.
10. Settlement-not-yet-open protection on cancellations and on reconcile — `ERR_PROGRAM_ALREADY_RECONCILING`.
11. Execution-finality requirement at reconcile — `ERR_PROGRAM_NOT_EXECUTION_FINAL`.
12. Reconciliation-window requirement on line and settlement work — `ERR_PROGRAM_NOT_RECONCILING`.
13. Programme-phase requirements on operational actions — `ERR_PROGRAM_NOT_CONFIRMED`, `ERR_PROGRAM_NOT_IN_EXECUTION`, `ERR_PROGRAM_WINDOW_NOT_OPEN`.
14. Supplier insurance sufficiency — `ERR_SUPPLIER_INSURANCE_INSUFFICIENT`.
15. Supplier approval posture — `ERR_SUPPLIER_NOT_APPROVED`.
16. Staff credential validity — `ERR_CREDENTIAL_EXPIRED`.
17. Staff employment posture — `ERR_STAFF_INACTIVE`.
18. Guest accessibility — `ERR_ACCESSIBILITY_UNMET`.
19. Permit coverage — `ERR_PERMIT_NOT_APPROVED`.
20. Permit lead time — `ERR_PERMIT_LEAD_TIME_INSUFFICIENT`.
21. Programme-window containment of elements and segments — `ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW`.
22. Venue occupation geometry — `ERR_VENUE_TURNOVER_CONFLICT`.
23. Staff shift overlap — `ERR_STAFF_ASSIGNMENT_OVERLAP`.
24. Staff rest gap — `ERR_STAFF_REST_GAP_VIOLATION`.
25. Staff daily ceiling — `ERR_STAFF_DAILY_LIMIT_EXCEEDED`.
26. Check-in windows — `ERR_CHECKIN_WINDOW_NOT_OPEN`.
27. Departure and delivery due times — `ERR_SEGMENT_NOT_DUE`, `ERR_ELEMENT_NOT_STARTED`.
28. Production-timeline acyclicity — `ERR_ELEMENT_DEPENDENCY_CYCLE`.
29. Weather-alternative wiring legality — `ERR_INVALID_WEATHER_ALTERNATIVE`.
30. Venue capacity — `ERR_VENUE_CAPACITY_EXCEEDED`.
31. Vehicle seat capacity — `ERR_SEGMENT_CAPACITY_EXCEEDED`.
32. Manifest uniqueness — `ERR_DUPLICATE_MANIFEST_ENTRY`.
33. Negotiation round ceiling — `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.
34. Cross-programme consistency of a move target or an assignment target — `ERR_SEGMENT_PROGRAM_MISMATCH`.
35. Staff role and polymorphic-target coherence — `ERR_STAFF_ROLE_MISMATCH`.
36. Non-empty manifest at departure — `ERR_EMPTY_MANIFEST`.
37. Presence of an active supplier contract — `ERR_NO_ACTIVE_SUPPLIER_CONTRACT`.
38. Predecessor delivery — `ERR_PREDECESSOR_NOT_DELIVERED`.
39. Availability of a rain plan — `ERR_NO_WEATHER_ALTERNATIVE`.
40. Non-empty reconcilable set — `ERR_NO_RECONCILABLE_ELEMENTS`.
41. All lines approved before invoicing — `ERR_RECONCILIATION_LINES_PENDING`.
42. Contract still active at settlement approval — `ERR_CONTRACT_NOT_ACTIVE`.
43. Non-empty element set at design lock — `ERR_PROGRAM_HAS_NO_ELEMENTS`.
44. No on-site staffing before design unlock — `ERR_PROGRAM_ALREADY_STAFFED_ON_SITE`.
45. Markup band — `ERR_MARKUP_PCT_OUT_OF_BAND`.
46. Variance explanation — `ERR_VARIANCE_REASON_REQUIRED`.
47. Settlement within open payable — `ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE`.
48. No already-paid settlement blocking the action — `ERR_SETTLEMENT_ALREADY_PAID`.
49. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`.

The rationale behind the ordering is worth internalising, because it explains the counter-intuitive placements. Insurance and credential compliance (bands 14 to 17) deliberately outrank all scheduling geometry (bands 22 to 27): the DMC may not put an uninsured coach operator or an uncredentialed greeter in front of a client under any scheduling circumstance, so a request that is both uninsured and double-booked reports the insurance failure. Fiscal checks (bands 45 to 48) run last because money figures only become meaningful once the operational picture is legal. And segregation of duties sits at the very bottom so that an operator who is genuinely barred from an action learns that only after every other aspect of the request has been found sound.

### 2.10. Segregation of Duties on the Contracting and Payment Desks

Two operations in this system may not be performed by the same human who performed their predecessor, and both comparisons are made on `X-User-ID`.

Countersigning a supplier contract requires that the acting `X-User-ID` differ from the `sent_by_user_id` recorded when the contract was last sent. A `SupplierManager` may not countersign a contract they themselves sent; the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Releasing funds on a settlement payment requires that the acting `X-User-ID` differ from the `approved_by_user_id` recorded at approval. A `Controller` may not release a payment they themselves approved, and the attempt carries the same `ERR_SEGREGATION_OF_DUTIES` code.

## 3. Business Logic & Workflows

### 3.1. Programme Intake and the Two Lifecycle Dimensions

A `ProgramDirector` opens the file for an incoming group by creating a **programme**, supplying the billing `client_name` (between 1 and 120 characters), the `group_name` as it will appear on airport signage (also 1 to 120 characters), the `arrival_date` marking the first instant of the programme window, the `departure_date` marking its last instant, and the `guaranteed_count` — the contractual head count the client warrants to the DMC, which must be at least 1. The `departure_date` must be strictly after the `arrival_date`. An optional `markup_pct` sets the disclosed markup applied to supplier cost on every reconciliation line; when omitted it defaults to `0.18`, and whether supplied or defaulted it must be at least `0.05` and at most `0.35`, with anything outside that band refused as `ERR_MARKUP_PCT_OUT_OF_BAND`.

A newly created programme starts with `execution_status` of `DRAFT` and `settlement_status` of `NOT_STARTED`, with `invoice_issued_at` null and with every derived count and money field at zero: `element_count`, `open_element_count`, `actual_attendance_total`, `estimated_client_total_cents`, `final_subtotal_cents`, `disclosed_markup_cents`, `management_fee_cents`, `final_client_total_cents`, `supplier_gross_payable_cents`, `supplier_settled_cents`, `supplier_open_payable_cents`, `credit_note_cents`, `seated_guest_count`, `staffing_gap_count` and `unseated_guest_count`.

The two dimensions advance independently. The **execution dimension** runs `DRAFT` → `DESIGN_LOCKED` → `CONFIRMED` → `IN_EXECUTION` → `COMPLETED`, with `CANCELLED` reachable from any of the first four and with `COMPLETED` and `CANCELLED` both terminal. The **settlement dimension** runs `NOT_STARTED` → `RECONCILING` → `CLIENT_INVOICED` → `SETTLED`, with a `CREDITED` detour that returns to `RECONCILING`, and only `SETTLED` is terminal. Neither dimension constrains the other's transition legality directly; where one dimension does gate the other, the gate is stated explicitly below.

Locking the design moves `execution_status` from `DRAFT` to `DESIGN_LOCKED` and is the point at which the element set is frozen. Two things are checked at the lock: the programme must already have at least one element, or the request is refused with `ERR_PROGRAM_HAS_NO_ELEMENTS`, and `markup_pct` must still sit within the `0.05`-to-`0.35` band, or the request is refused with `ERR_MARKUP_PCT_OUT_OF_BAND`. The lock recomputes `element_count` and `open_element_count` and increments the programme's `version`. Because the design is frozen, adding an element to a programme whose `execution_status` is anything other than `DRAFT` is refused with `ERR_PROGRAM_DESIGN_LOCKED`, and so is reshaping an existing element.

The lock is reversible. Unlocking returns `DESIGN_LOCKED` → `DRAFT`, but only while the money has not started moving — `settlement_status` must still be `NOT_STARTED` — and only while nobody has actually worked the programme: if any staff assignment of the programme has reached `CHECKED_IN` or `COMPLETED`, the unlock is refused with `ERR_PROGRAM_ALREADY_STAFFED_ON_SITE`. A successful unlock increments the programme's `version`.

Confirming the programme to the client moves `DESIGN_LOCKED` → `CONFIRMED` and is the moment the estimate is frozen. Confirmation requires that no element of the programme sit in `PERMIT_BLOCKED` — otherwise `ERR_PERMIT_NOT_APPROVED` — and that every element of the programme still in `PLANNED` or `READY` be covered by a supplier contract for the same programme and the same supplier whose `status` is `ACTIVE`; an uncovered element yields `ERR_NO_ACTIVE_SUPPLIER_CONTRACT`. On success the estimate variant of the client-total calculation runs and its result is written to `estimated_client_total_cents`, and the programme's `version` increments.

Opening on-site execution moves `CONFIRMED` → `IN_EXECUTION` and is an `OperationsCoordinator` action taken once the group has actually landed. It requires that the logical clock have reached the programme's `arrival_date` — a clock strictly earlier than `arrival_date` is refused with `ERR_PROGRAM_WINDOW_NOT_OPEN` — and it is only legal from `CONFIRMED`, with any other source state refused as `ERR_PROGRAM_NOT_CONFIRMED`.

Cancelling a programme is available from `DRAFT`, `DESIGN_LOCKED`, `CONFIRMED` or `IN_EXECUTION`, accepts an optional `cancel_reason`, and is refused with `ERR_PROGRAM_ALREADY_RECONCILING` if `settlement_status` has left `NOT_STARTED`. The cancellation is a two-pronged cascade. Every element of the programme in `PLANNED`, `PERMIT_BLOCKED` or `READY` moves to `CANCELLED`, and each of those element transitions independently computes and stamps its own cancellation penalty and runs its own staff-release cascade, exactly as if the element had been cancelled individually. Every transport segment of the programme in `SCHEDULED` moves to `CANCELLED`, and each of those segment transitions independently runs its own manifest-release cascade. The programme's `open_element_count` is then recomputed to zero and its `version` increments.

### 3.2. Curating the Element Set: Venues, Production Timelines and Rain Plans

Venues are registered independently of programmes by a `ProgramDirector`, who supplies the venue's `name`, its `capacity_seated` for seated dinners and its `capacity_reception` for standing receptions (both at least 0), plus three optional properties: `turnover_buffer_minutes`, the strike-and-reset time required after an occupation ends before the next may begin, which defaults to 90 minutes and must be at least 0; `requires_special_venue_permit`, defaulting to false, which when true means an element booked here needs an approved special-venue permit before it can be marked ready; and `status`, which is `ACTIVE` by default and may be `SUSPENDED`.

Within a `DRAFT` programme, the director curates **program elements** — the activities, dine-arounds, off-premise events and transfer blocks that make up the programme. Each element is created with the `program_id` it belongs to, the `supplier_id` delivering it, an `element_type` drawn from `ACTIVITY`, `DINE_AROUND`, `OFF_PREMISE_EVENT` and `TRANSFER_BLOCK`, the `title` that will print on the production timeline, a `starts_at` and `ends_at` bounding the venue occupation (with `ends_at` strictly after `starts_at`), the `planned_headcount` and `guaranteed_headcount` (both at least 0), the `per_person_cost_cents` the supplier charges per billed head (at least 0), and the `expected_program_version` guard described in §2.5. Optionally it carries a `venue_id` — null for transfer blocks, which occupy no venue — a `predecessor_element_id` naming the production-timeline element that must be delivered first, an `alternative_for_element_id` naming the element for which this one is the rain plan, and an `is_weather_dependent` flag defaulting to false. A new element lands in `PLANNED`, and the create recomputes the programme's `element_count` and `open_element_count` and increments the programme's `version`.

Elements must sit inside the programme they belong to. An element whose `starts_at` falls before the programme's `arrival_date`, or whose `ends_at` falls after the last instant the programme's `departure_date` names, is refused with `ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW`. A `departure_date` filed as a bare calendar date names the whole of that day, so the bound is that day's final instant and an `ends_at` anywhere on the departure day — 13:00 on it, say — is still inside the window, while the midnight that begins the following day is not; a `departure_date` filed as a full instant is itself the bound. The same containment rule applies to transport segments, whose `depart_at` must be at or after `arrival_date` and whose `arrive_at` must be at or before that same upper bound.

Venue occupation geometry deserves careful reading, because its treatment of adjacency is asymmetric. An element occupies its venue over the **half-open** interval from `starts_at` inclusive to `ends_at` exclusive, and the venue's turnover buffer is attached **forward only**, to the tail of the incumbent occupation. Consider a candidate element and every incumbent element at the same venue whose `status` is `PLANNED`, `PERMIT_BLOCKED`, `READY` or `DELIVERED`. The candidate is refused when its `starts_at` falls strictly before the incumbent's `ends_at` advanced by the venue's `turnover_buffer_minutes` **and** the incumbent's `starts_at` falls strictly before the candidate's `ends_at`. Two consequences are pinned by that geometry: a candidate that ends exactly when an incumbent begins is accepted, because no buffer is required in front of an incumbent; but a candidate that begins exactly when an incumbent ends is refused unless the full turnover buffer has already elapsed. The rejection code is `ERR_VENUE_TURNOVER_CONFLICT`.

Venue capacity is checked whenever `venue_id` is non-null, and which capacity applies depends on the format. For a `DINE_AROUND` element, `planned_headcount` may not exceed the venue's `capacity_seated`; for an `ACTIVITY` or an `OFF_PREMISE_EVENT`, it may not exceed `capacity_reception`. The venue's `status` must also be `ACTIVE`. Any of these failures is reported as `ERR_VENUE_CAPACITY_EXCEEDED`.

The production timeline formed by `predecessor_element_id` is a directed graph, and it must stay acyclic. Following the predecessor chain transitively from a candidate element must terminate without ever arriving back at the candidate; a self-reference or any longer cycle is refused with `ERR_ELEMENT_DEPENDENCY_CYCLE`. The rain-plan graph formed by `alternative_for_element_id` has its own wiring rules: when supplied, it must reference an element of the same programme, that element must itself be flagged `is_weather_dependent`, it must not be the same element as the candidate's own `predecessor_element_id`, and the referenced element must not itself already carry a non-null `alternative_for_element_id` — a rain plan for a rain plan is not permitted. Violations are refused with `ERR_INVALID_WEATHER_ALTERNATIVE`.

While the programme is still `DRAFT`, a director may reshape an existing element: retitle it via `title`, re-scale it via `planned_headcount`, rewire the production timeline via `predecessor_element_id`, rewire the rain plan via `alternative_for_element_id`, or flip `is_weather_dependent`. This is the only way an existing element's graph edges change, so it is where the acyclicity and rain-plan wiring checks bite a second time, and both `ERR_ELEMENT_DEPENDENCY_CYCLE` and `ERR_INVALID_WEATHER_ALTERNATIVE` apply here exactly as they do at creation. Reshaping increments the element's own `version` and deliberately leaves the programme's `element_count` and `open_element_count` untouched, since no element joined or left the set. Attempting it once the programme has left `DRAFT` is refused with `ERR_PROGRAM_DESIGN_LOCKED`.

### 3.3. The Vendor File and the Contracting Cycle

A `SupplierManager` onboards each local supplier into the vendor file with its `legal_name`, its `supplier_type` — one of `VENUE_SERVICES`, `TRANSPORT`, `ACTIVITY` or `STAFFING` — and its certificate-of-insurance data: `insurance_expires_on`, the inclusive expiry instant of the certificate, and `insurance_liability_limit_cents`, the per-occurrence liability limit carried on it (at least 0). Two optional flags complete the record: `coi_verified`, defaulting to false, which the risk desk sets once it has actually read the certificate document, and `status`, which starts at `PROSPECT` and may be moved to `APPROVED` or `SUSPENDED`. The same manager may later patch a supplier's `insurance_expires_on`, `insurance_liability_limit_cents`, `coi_verified` or `status`, which increments the supplier's `version`.

Contracting is scoped to one programme and one supplier at a time. Drafting a **supplier contract** requires the `program_id`, the `supplier_id`, the `contract_value_cents` (at least 1) and the `required_liability_limit_cents` — the minimum insurance limit the DMC demands of this supplier for this programme (at least 0). Two terms are optional: `deposit_pct`, the fraction of contract value payable as deposit at countersignature, which defaults to `0.3` and must lie between 0 and 1 inclusive; and `cancellation_tier`, either `STANDARD` or `STRICT`, defaulting to `STANDARD`. A freshly drafted contract sits in `DRAFT` with `round_count`, `deposit_due_cents` and `deposit_paid_cents` all zero and with `sent_by_user_id` and `countersigned_by_user_id` both null.

The negotiation is a genuine cycle. Sending the contract advances it `DRAFT` → `SENT`, and re-sending after a counter-offer advances it `COUNTERED` → `SENT`; both writes stamp `sent_by_user_id` with the acting `X-User-ID`, add one to `round_count`, and increment the contract's `version`. A send from `DRAFT` additionally requires that the supplier's `status` be `APPROVED` — otherwise `ERR_SUPPLIER_NOT_APPROVED` — and that the supplier's insurance actually satisfy this contract: `coi_verified` must be true, `insurance_expires_on` must be at or after the logical clock's current instant, and `insurance_liability_limit_cents` must be at least the contract's `required_liability_limit_cents`. Any of those three failures is reported as `ERR_SUPPLIER_INSURANCE_INSUFFICIENT`.

The supplier's own move is the counter-offer, which advances `SENT` → `COUNTERED` and is the only write a `Supplier` may perform. It carries a `countered_value_cents` figure that overwrites the contract's `contract_value_cents`, and it requires that `X-User-ID` match the contract's `supplier_id`, failing with `ERR_NOT_RESOURCE_OWNER` otherwise. Both the counter and the send are bounded: the DMC permits at most three negotiation rounds, so a send or a counter attempted while `round_count` has already reached 3 is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. The `SENT` → `COUNTERED` → `SENT` loop can therefore turn at most three times before somebody has to either countersign or walk away.

Countersignature closes the negotiation, advancing either `SENT` → `ACTIVE` or `COUNTERED` → `ACTIVE`. It re-checks the insurance triple — `insurance_expires_on` at or after the logical clock and `insurance_liability_limit_cents` at least `required_liability_limit_cents`, with failure reported as `ERR_SUPPLIER_INSURANCE_INSUFFICIENT` — and it enforces the segregation-of-duties rule of §2.10 against `sent_by_user_id`. On success it stamps `countersigned_by_user_id` with the acting `X-User-ID`, computes `deposit_due_cents` as the contract value multiplied by `deposit_pct` and rounded half up to whole cents, sets `deposit_paid_cents` equal to `deposit_due_cents` — the deposit is treated as banked at signature — and increments the contract's `version`.

Termination is available from `DRAFT`, `SENT`, `COUNTERED` or `ACTIVE` and accepts an optional `termination_note`. It is blocked while money has already moved: if any settlement payment against this contract has reached `APPROVED` or `PAID`, the request is refused with `ERR_SETTLEMENT_ALREADY_PAID`. A successful termination resets `deposit_paid_cents` to zero, cascades into the operational plan by moving every element of the same programme and the same supplier that is still in `PLANNED`, `PERMIT_BLOCKED` or `READY` to `CANCELLED` — with each of those element transitions computing and stamping its own cancellation penalty and running its own staff-release cascade — and increments the contract's `version`.

A contract's other exit is not requested at all. When a programme's settlement dimension reaches `SETTLED`, every contract of that programme still in `ACTIVE` is moved `ACTIVE` → `CLOSED` by the server, each such contract having its `version` incremented. `CLOSED` and `TERMINATED` are both terminal.

### 3.4. Permitting with the Issuing Authorities

Street closures, unusual venues and off-premise alcohol service all need municipal or licensing-board authorisation, and a `PermitOfficer` owns that conversation end to end. A **permit** is opened against a single element by supplying the `element_id`, the `permit_type` — one of `STREET_CLOSURE`, `SPECIAL_VENUE` or `OFF_PREMISE_ALCOHOL` — the `authority_name` of the issuing body, and `lead_time_days_required`, the minimum whole days that must separate submission from the element's start (at least 0). A new permit sits in `DRAFT` with `resubmission_count` zero, `submitted_at` and `decision_at` null, and `conditions_note` null.

Submission advances the permit `DRAFT` → `SUBMITTED` and stamps `submitted_at` with the logical clock instant. The element being authorised must be in `PLANNED` or `PERMIT_BLOCKED`, and a submission against an element in any other status is refused with `ERR_INVALID_STATE_TRANSITION`. The lead-time test is the substantive one: take the interval from the logical clock's current instant to the element's `starts_at`, express it in whole 24-hour days by discarding any fractional remainder, and require that the result be at least the permit's `lead_time_days_required`. A shortfall is refused with `ERR_PERMIT_LEAD_TIME_INSUFFICIENT`.

The authority's answer is recorded as a `decision` of `APPROVED`, `DENIED` or `CONDITIONS_REQUESTED`, always from `SUBMITTED`, and all three branches stamp `decision_at` with the logical clock instant and increment the permit's `version`. The three branches are otherwise very different.

An `APPROVED` decision may unblock the element. If the element identified by the permit's `element_id` is sitting in `PERMIT_BLOCKED` and, after this approval, no permit of that element remains in `DRAFT`, `SUBMITTED`, `CONDITIONS_REQUESTED` or `DENIED`, then the element itself moves `PERMIT_BLOCKED` → `PLANNED` and has its own `version` incremented. That is the cycle edge on the element machine: an element can travel `PLANNED` → `PERMIT_BLOCKED` → `PLANNED` and back out again as its permits are refused and re-won.

A `CONDITIONS_REQUESTED` decision returns the permit for revision and requires a non-empty `conditions_note` in the request body describing what the authority wants; a missing or empty note is refused with `ERR_INVALID_REQUEST`. The note is stored on the permit. From `CONDITIONS_REQUESTED` the officer may submit again, which advances `CONDITIONS_REQUESTED` → `SUBMITTED`, re-stamps `submitted_at`, adds one to `resubmission_count`, and applies exactly the same lead-time test as a first submission — with the clock having moved on, a revision that took too long to prepare will fail with `ERR_PERMIT_LEAD_TIME_INSUFFICIENT` even though the original submission passed. That is the permit cycle: `SUBMITTED` → `CONDITIONS_REQUESTED` → `SUBMITTED`, turnable any number of times.

A `DENIED` decision is the four-level cascade referenced in §2.7, and it is the most consequential single write in the permitting workflow. First, the element identified by `element_id`, if its status is `PLANNED` or `READY`, moves to `PERMIT_BLOCKED`, with its own `version` incremented; the programme's `open_element_count` is recomputed and is unchanged by this, because `PERMIT_BLOCKED` is still an open status. Second, caused by that block, every staff assignment against that element whose status is `PROPOSED` or `CONFIRMED` moves to `RELEASED`. Third, caused by each of those releases, the assignment's staff member has `confirmed_minutes_total` decremented by that assignment's scheduled minutes and the programme's `staffing_gap_count` is incremented by one. `APPROVED` and `DENIED` are both terminal permit states.

### 3.5. Ground Transportation and Manifest Management

An `OperationsCoordinator` schedules each ground movement as a **transport segment** carrying the `program_id`, a `segment_type` of `ARRIVAL_TRANSFER`, `DEPARTURE_TRANSFER`, `SHUTTLE_LOOP` or `DINE_AROUND_LEG`, the operator's `vehicle_code` (free text, not a managed resource), the `origin` pick-up label and `destination` drop-off label, the scheduled `depart_at` and `arrive_at` instants with `arrive_at` strictly after `depart_at`, the vehicle's `seat_capacity` (at least 1), and an optional `wheelchair_accessible` flag defaulting to false. Segments begin in `SCHEDULED` with `booked_seat_count` zero and `departed_at` null, and must fall inside the programme window as described in §3.2.

Guests are manifested onto a segment one **manifest entry** at a time, supplying the `segment_id`, the guest's `guest_ref` reference code, the `guest_name` as it will print on the manifest, an optional `seat_count` defaulting to 1 and never below 1 (a guest travelling with a companion may take two seats), and an optional `mobility_assist` flag defaulting to false. Entries begin in `ASSIGNED` with `move_count` zero.

Seat arithmetic is the invariant of this subsection. A segment's `booked_seat_count` is the sum of `seat_count` over that segment's entries whose status is `ASSIGNED` or `CHECKED_IN`; entries in `RELEASED` or `NO_SHOW` are excluded. The capacity gate is generous at the boundary: a manifest write is refused only when the segment's current `booked_seat_count` plus the candidate's `seat_count` is **strictly greater** than the segment's `seat_capacity`, so filling a vehicle to exactly its capacity succeeds. Exceeding it yields `ERR_SEGMENT_CAPACITY_EXCEEDED`. A guest requiring `mobility_assist` may only be placed on a segment whose `wheelchair_accessible` is true, with failure reported as `ERR_ACCESSIBILITY_UNMET`. And the same `guest_ref` may not appear twice on one segment among entries in `ASSIGNED` or `CHECKED_IN`, with a collision reported as `ERR_DUPLICATE_MANIFEST_ENTRY`. All three gates apply both when manifesting a guest and when moving one. Above the segment level, the programme's `seated_guest_count` is the sum of `booked_seat_count` across that programme's segments, and it is recomputed whenever any segment's occupancy changes.

Moving a guest to another vehicle is a **self-transition**: the entry stays in `ASSIGNED` while its `segment_id` changes to the supplied `target_segment_id`. It requires the entry to be in `ASSIGNED`, both the source and the target segment to be in `SCHEDULED` (otherwise `ERR_INVALID_STATE_TRANSITION`), the `target_segment_id` to differ from the entry's current `segment_id` (otherwise `ERR_INVALID_REQUEST`), and the target segment to belong to the same programme as the source (otherwise `ERR_SEGMENT_PROGRAM_MISMATCH`). The three manifest gates above are then applied against the target. A successful move adds one to `move_count`, subtracts the entry's `seat_count` from the source segment's `booked_seat_count` and adds it to the target's, and increments the entry's `version`. Crucially, the programme's `seated_guest_count` is recomputed and comes out **unchanged** — seats are conserved by a move, never created or destroyed.

Curb-side check-in advances an entry `ASSIGNED` → `CHECKED_IN`. The segment must still be `SCHEDULED`, otherwise `ERR_INVALID_STATE_TRANSITION`, and the programme's `execution_status` must be `IN_EXECUTION`, otherwise `ERR_PROGRAM_NOT_IN_EXECUTION`. The window opens two hours before the wheels are due to turn: the logical clock must have reached the segment's `depart_at` less 120 minutes, and an earlier attempt is refused with `ERR_CHECKIN_WINDOW_NOT_OPEN`. Check-in leaves `booked_seat_count` untouched, since both `ASSIGNED` and `CHECKED_IN` count toward occupancy, and increments the entry's `version`.

Departure advances the segment `SCHEDULED` → `DEPARTED` and closes the manifest. It requires the programme to be `IN_EXECUTION` (`ERR_PROGRAM_NOT_IN_EXECUTION`), the logical clock to have reached the segment's `depart_at` (`ERR_SEGMENT_NOT_DUE`), and the segment to have at least one seat booked (`ERR_EMPTY_MANIFEST`). On success `departed_at` is stamped from the logical clock; every entry still in `ASSIGNED` at that instant moves to `NO_SHOW`, each such entry subtracting its own `seat_count` from the segment's `booked_seat_count` and having its own `version` incremented; `booked_seat_count` is then recomputed over the entries still in `ASSIGNED` or `CHECKED_IN`, which after the no-show sweep means the checked-in guests alone; the programme's `seated_guest_count` is recomputed; every staff assignment against this segment in `CHECKED_IN` moves to `COMPLETED`, running the actual variant of the labour-cost calculation; and the segment's `version` increments.

Cancelling a scheduled movement, with an optional `cancel_reason`, is the three-level cascade referenced in §2.7. Every entry of the segment in `ASSIGNED` or `CHECKED_IN` moves to `RELEASED`; caused by each such release, the segment's `booked_seat_count` is decremented by that entry's `seat_count` and the programme's `unseated_guest_count` is incremented by one; and caused by that, the programme's `seated_guest_count` is recomputed as the sum of `booked_seat_count` across the programme's segments. Separately, every staff assignment against this segment in `PROPOSED` or `CONFIRMED` moves to `RELEASED`. The segment's `version` increments. `DEPARTED` and `CANCELLED` are both terminal for a segment, as `RELEASED` and `NO_SHOW` are for a manifest entry.

### 3.6. The Staffing Plan: Credentialing, Rest and On-Site Attribution

A `ProgramDirector` registers each on-site body as a **staff member** with a `full_name`, a `role_type` of `COORDINATOR`, `GREETER` or `ACTIVITY_LEAD`, the two credential expiries `badge_expires_on` (venue and airport access) and `first_aid_expires_on` (first-aid certification), both inclusive, and the `pay_rate_cents_per_hour` used for labour costing (at least 0). Three optional properties tune the person's working rules: `min_rest_minutes`, the minimum minutes that must separate the end of one assignment from the start of the next, defaulting to 600 — ten hours — and never below 0; `max_daily_minutes`, the ceiling on confirmed assignment minutes within one UTC calendar day, defaulting to 720 — twelve hours — and never below 0; and `status`, either `ACTIVE` (the default) or `INACTIVE`. A member's `confirmed_minutes_total` accumulator starts at zero. All of `badge_expires_on`, `first_aid_expires_on`, `pay_rate_cents_per_hour`, `min_rest_minutes`, `max_daily_minutes` and `status` may later be patched, which re-derives the credential status and increments the member's `version`.

`credential_status` is never supplied by a client; it is derived on every read of a staff member against the logical clock, and it takes one of three values. Take the **earlier** of `badge_expires_on` and `first_aid_expires_on` — a person is only as credentialed as their weakest document. If that instant lies strictly before the logical clock, the status is `EXPIRED`. Otherwise, if it lies at or before the logical clock advanced by 14 days, the status is `EXPIRING`. Otherwise it is `VALID`. Comparisons are made at millisecond resolution, and a document expiring at exactly the clock's current instant is still in force — such a member reads `EXPIRING`, not `EXPIRED`.

Shifts are proposed as **staff assignments** carrying the `staff_id` of the person, the `program_id` being staffed, a `target_type` of either `ELEMENT` or `SEGMENT` acting as a polymorphic discriminator, the `role_type` performed on this shift, and the shift's `starts_at` and `ends_at` with `ends_at` strictly after `starts_at`. Exactly one of the two optional targets is populated according to the discriminator: `element_id` when `target_type` is `ELEMENT`, with `segment_id` left null, and `segment_id` when `target_type` is `SEGMENT`, with `element_id` left null. The assignment's `role_type` must equal the staff member's own `role_type`; that requirement and the discriminator coherence requirement are both enforced as `ERR_STAFF_ROLE_MISMATCH`. If the named `element_id` or `segment_id` belongs to a different programme than `program_id`, the proposal is refused with `ERR_SEGMENT_PROGRAM_MISMATCH`. A new assignment lands in `PROPOSED` with `check_in_at`, `completed_at` null and `planned_labor_cost_cents`, `actual_labor_cost_cents` both zero, and — importantly — **no credential, overlap, rest or daily check runs at proposal time**. Proposing is cheap; confirming is where the compliance work happens.

Confirmation advances the assignment `PROPOSED` → `CONFIRMED` and is where the eight-check gauntlet applies, in the order §2.9 fixes. The programme's `execution_status` must be `DESIGN_LOCKED`, `CONFIRMED` or `IN_EXECUTION`, otherwise `ERR_PROGRAM_NOT_CONFIRMED`. The staff member's `status` must be `ACTIVE`, otherwise `ERR_STAFF_INACTIVE`. The member's derived `credential_status` must be exactly `VALID` — an `EXPIRING` member is refused just as an `EXPIRED` one is, because the earliest of the two documents must lie strictly beyond the clock plus the 14-day window — with `ERR_CREDENTIAL_EXPIRED` as the code. The assignment's `role_type` must still match the member's, or `ERR_STAFF_ROLE_MISMATCH`. Then the three scheduling tests run, and then the labour cost is stamped.

Staff occupation geometry is **closed** at both ends and carries no buffer, which is the exact opposite of the venue treatment in §3.2. For the candidate shift and every incumbent shift of the same `staff_id` whose status is `CONFIRMED`, `CHECKED_IN` or `COMPLETED`, the candidate is refused when the candidate's `starts_at` is at or before the incumbent's `ends_at` **and** the incumbent's `starts_at` is at or before the candidate's `ends_at`. A shift beginning at precisely the instant another ends therefore collides and is refused with `ERR_STAFF_ASSIGNMENT_OVERLAP`, where a venue booking in the same position would have been accepted.

Rest is checked against the shifts that do **not** overlap. For every non-overlapping incumbent shift of the same `staff_id` in `CONFIRMED`, `CHECKED_IN` or `COMPLETED`, take the gap as the smaller of the absolute distance from the candidate's `starts_at` to the incumbent's `ends_at` and the absolute distance from the incumbent's `starts_at` to the candidate's `ends_at`, and require that gap to be at least the member's `min_rest_minutes`. A shorter gap is refused with `ERR_STAFF_REST_GAP_VIOLATION`.

The daily ceiling is a calendar-day sum. Add up the scheduled minutes of the member's assignments in `CONFIRMED`, `CHECKED_IN` or `COMPLETED` whose `starts_at` falls on the same UTC calendar day as the candidate's `starts_at`, add the candidate's own minutes, and require the result to be at most the member's `max_daily_minutes`. Exceeding it is refused with `ERR_STAFF_DAILY_LIMIT_EXCEEDED`.

A confirmation that clears all of that runs the **planned** variant of the labour-cost calculation, writes the result to `planned_labor_cost_cents`, adds the assignment's scheduled minutes to the member's `confirmed_minutes_total`, and increments the assignment's `version`.

The labour-cost calculation is a three-input rate ladder, and it differs between its two variants only in the minute basis it starts from. The **planned** variant, run at confirmation, uses the scheduled window: the whole minutes from the assignment's `starts_at` to its `ends_at`, independent of any check-in. The **actual** variant, run when an assignment reaches `COMPLETED`, uses the worked window: the whole minutes from `check_in_at` to `completed_at`; for an assignment that reached `NO_SHOW` without ever checking in, the minute basis is zero. From that minute basis the ladder proceeds identically. If the minute basis is zero, the cost is zero and no further work is done. Otherwise the billable minutes are the larger of the minute basis and the DMC's four-hour call-out minimum of 240 minutes — a greeter called out for a 90-minute airport meet is still paid for four hours. The regular leg is the smaller of the billable minutes and the eight-hour overtime threshold of 480 minutes; the overtime leg is whatever billable minutes exceed 480, and zero when none do. The regular leg's cents figure is the regular minutes divided by 60, multiplied by the member's `pay_rate_cents_per_hour`, rounded half up to whole cents. The overtime leg's cents figure is the overtime minutes divided by 60, multiplied by `pay_rate_cents_per_hour`, multiplied again by the overtime multiplier of 1.5, and rounded half up to whole cents. The two rounded legs are then added to give the cost. One consequence is worth flagging to whoever writes the tests: a coordinator who checks in late and whose element finishes early bills fewer worked minutes than planned, yet the 240-minute call-out floor can make the actual figure identical to the planned figure for short shifts.

On-site check-in advances the assignment `CONFIRMED` → `CHECKED_IN` and stamps `check_in_at` from the logical clock. It is the operation where identity matters: the acting `X-User-ID` must equal the assignment's `staff_id`, or the request is refused with `ERR_NOT_RESOURCE_OWNER`. The programme must be `IN_EXECUTION` (`ERR_PROGRAM_NOT_IN_EXECUTION`), and the logical clock must lie within the window that opens 60 minutes before the shift's `starts_at` and closes at its `ends_at`; outside that window the attempt is refused with `ERR_CHECKIN_WINDOW_NOT_OPEN`.

Assignments leave the board in three ways, and the accounting differs. Reaching `COMPLETED` from `CHECKED_IN` is never requested directly — it is cascaded when the element the shift served is delivered, or when the segment it served departs — and it stamps `completed_at` from the logical clock, runs the actual variant of the labour-cost calculation into `actual_labor_cost_cents`, and increments the assignment's `version`. Reaching `NO_SHOW` from `CONFIRMED` is likewise cascaded, from the delivery of an element whose confirmed staff never checked in; it sets `actual_labor_cost_cents` to zero, subtracts the assignment's scheduled minutes from the member's `confirmed_minutes_total`, adds one to the programme's `staffing_gap_count`, and increments the assignment's `version`. Reaching `RELEASED` is available from either `PROPOSED` or `CONFIRMED`, either by a director's explicit release with an optional `release_reason`, or by cascade from an element becoming `PERMIT_BLOCKED`, `CANCELLED` or `WEATHER_SWITCHED`, or from a segment being cancelled. Release is asymmetric in its bookkeeping: when the prior status was `CONFIRMED`, the member's `confirmed_minutes_total` is decremented by the assignment's scheduled minutes and the programme's `staffing_gap_count` is incremented by one; when the prior status was `PROPOSED`, neither `confirmed_minutes_total` nor `staffing_gap_count` changes, because a proposal never reserved anything. Either way the assignment's `version` increments. `COMPLETED`, `RELEASED` and `NO_SHOW` are all terminal.

### 3.7. On-Site Execution: Ready, Deliver, and the Weather Alternative

Marking an element production-ready advances it `PLANNED` → `READY` and is the coordinator's assertion that everything upstream is in place. Five conditions are checked. The programme's `execution_status` must be `CONFIRMED` or `IN_EXECUTION`, otherwise `ERR_PROGRAM_NOT_CONFIRMED`. No permit of this element may remain in `DRAFT`, `SUBMITTED`, `CONDITIONS_REQUESTED` or `DENIED`; and additionally, when the element's venue has `requires_special_venue_permit` set to true, a permit of this element with `permit_type` of `SPECIAL_VENUE` and status `APPROVED` must exist. Both permit failures report `ERR_PERMIT_NOT_APPROVED`. A supplier contract for this element's programme and supplier with status `ACTIVE` must exist, otherwise `ERR_NO_ACTIVE_SUPPLIER_CONTRACT`. And the production timeline must have caught up: either `predecessor_element_id` is null, or the element it names has reached `DELIVERED`; anything else is refused with `ERR_PREDECESSOR_NOT_DELIVERED`. Success increments the element's `version`.

Delivery advances `READY` → `DELIVERED` and is the moment attendance becomes a fact. It requires the programme to be `IN_EXECUTION` (`ERR_PROGRAM_NOT_IN_EXECUTION`), the logical clock to have reached the element's `starts_at` (`ERR_ELEMENT_NOT_STARTED`), and an `actual_headcount` of at least 0 to be present in the request body (`ERR_INVALID_REQUEST` when it is missing). On success the supplied `actual_headcount` is stored on the element and `delivered_at` is stamped from the logical clock. Then the staffing consequences fire in two symmetric branches: every staff assignment against this element in `CHECKED_IN` moves to `COMPLETED`, each running the actual variant of the labour-cost calculation into its `actual_labor_cost_cents`; and every staff assignment against this element still in `CONFIRMED` moves to `NO_SHOW`, each setting `actual_labor_cost_cents` to zero, decrementing its member's `confirmed_minutes_total` and incrementing the programme's `staffing_gap_count`. The programme's `actual_attendance_total` — the sum of `actual_headcount` over elements in `DELIVERED` — and its `open_element_count` are recomputed. Finally, if `open_element_count` has reached zero while the programme is `IN_EXECUTION`, the programme itself advances `IN_EXECUTION` → `COMPLETED`, recomputing `actual_attendance_total` and incrementing the programme's `version`. The element's own `version` increments regardless.

The rain plan is exercised by a weather switch, advancing the outdoor element `READY` → `WEATHER_SWITCHED` and promoting its indoor stand-in. Four conditions gate it. The element must carry `is_weather_dependent` set to true, otherwise `ERR_ELEMENT_NOT_WEATHER_DEPENDENT`. The programme must be `IN_EXECUTION`, otherwise `ERR_PROGRAM_NOT_IN_EXECUTION`. A stand-in must exist: the server looks for elements whose `alternative_for_element_id` names this element and whose status is `PLANNED`. When that set is empty the request is refused with `ERR_NO_WEATHER_ALTERNATIVE`; when it holds more than one candidate the server selects the one with the earliest `starts_at`, breaking ties by earliest `created_at`. And the selected stand-in must itself be permit-clean: it may carry no permit in `DRAFT`, `SUBMITTED`, `CONDITIONS_REQUESTED` or `DENIED`, or the switch is refused with `ERR_PERMIT_NOT_APPROVED`. On success the selected alternative advances `PLANNED` → `READY`; every staff assignment against the switched-away element in `PROPOSED` or `CONFIRMED` moves to `RELEASED`, each such release decrementing its member's `confirmed_minutes_total` when the prior status was `CONFIRMED` and incrementing the programme's `staffing_gap_count`; the programme's `open_element_count` is recomputed; and the element's `version` increments. Because the switch resolves one open element while opening another, the bubble-up to `COMPLETED` described above is re-evaluated here too.

Cancelling a single element, with an optional `cancel_reason`, is available from `PLANNED`, `PERMIT_BLOCKED` or `READY`, whether requested directly by a `ProgramDirector` or cascaded from a programme cancellation or a contract termination. It is blocked once the money is moving: if the programme's `settlement_status` has left `NOT_STARTED`, the request is refused with `ERR_PROGRAM_ALREADY_RECONCILING`. On success the cancellation-penalty calculation runs and its result is stamped onto the element's `cancellation_penalty_cents`; every staff assignment against the element in `PROPOSED` or `CONFIRMED` moves to `RELEASED`, each decrementing its member's `confirmed_minutes_total` when the prior status was `CONFIRMED` and incrementing the programme's `staffing_gap_count`; the programme's `open_element_count` is recomputed; if that count reaches zero while the programme is `IN_EXECUTION`, the programme advances `IN_EXECUTION` → `COMPLETED`; and the element's `version` increments. `DELIVERED`, `WEATHER_SWITCHED` and `CANCELLED` are all terminal for an element.

The cancellation penalty is a two-schedule tier ladder read against the logical clock. First compute the days to service: take the interval from the logical clock's current instant to the element's `starts_at` and express it in whole 24-hour days, discarding any fractional remainder. When the element's start has already passed the figure is negative, which places the cancellation in the harshest band of whichever schedule applies. The schedule comes from the supplier contract governing this element, selected as follows: consider contracts whose `program_id` matches the element's programme and whose `supplier_id` matches the element's supplier and whose status is one of `SENT`, `COUNTERED`, `ACTIVE` or `TERMINATED`; rank them with `ACTIVE` first, then `TERMINATED`, then `COUNTERED`, then `SENT`, breaking ties by the latest `created_at`; and if no contract qualifies at all, treat the cancellation tier as `STANDARD`. On the `STANDARD` schedule, a cancellation at 30 or more whole days out costs nothing; at 15 to 29 days it costs a quarter of the element's planned value; at 7 to 14 days it costs half; and inside 7 days it costs the whole planned value. On the `STRICT` schedule, even a cancellation 45 or more days out costs a tenth; at 30 to 44 days it costs 35 hundredths; at 8 to 29 days it costs three quarters; and inside 8 days it costs the whole planned value. All the day comparisons are inclusive, so exactly 30 whole days out on `STANDARD` attracts no penalty at all while 29 attracts a quarter. The penalty itself is the element's `planned_headcount` multiplied by its `per_person_cost_cents` multiplied by the tier fraction, rounded half up to whole cents.

### 3.8. Reconciliation: Actual Attendance versus Guaranteed Counts

Reconciliation is the settlement dimension's first move, advancing `settlement_status` from `NOT_STARTED` to `RECONCILING`. Three conditions gate it: `settlement_status` must still be `NOT_STARTED`, or the request is refused with `ERR_PROGRAM_ALREADY_RECONCILING`; the execution dimension must have reached a final state, either `COMPLETED` or `CANCELLED`, or the request is refused with `ERR_PROGRAM_NOT_EXECUTION_FINAL`; and at least one element of the programme must be in `DELIVERED` or `CANCELLED`, since there is nothing to reconcile otherwise, with the empty case refused as `ERR_NO_RECONCILABLE_ELEMENTS`.

Opening reconciliation materialises exactly one **reconciliation line** for each element of the programme in `DELIVERED` or `CANCELLED`, created in ascending `starts_at` order of the underlying element with ascending `created_at` as the tie-break. Each line copies the `program_id`, the element's `element_id` and the element's `supplier_id` — the supplier is denormalised onto the line so that settlement can be grouped by payee — and takes a `line_kind` of `DELIVERY` for a delivered element or `CANCELLATION_PENALTY` for a cancelled one. Each line also snapshots the element's `guaranteed_headcount` and `actual_headcount` as they stood at reconcile time, with `actual_headcount` recorded as 0 on a `CANCELLATION_PENALTY` line. Every line lands in `DRAFT` with `variance_reason` null. The programme's `actual_attendance_total` is recomputed and its `version` increments.

Each created line then runs the final head-count rule and the line-amount rule in that order. The **final** billable head count exists to protect the supplier from attrition: take the element's `guaranteed_headcount`, multiply it by 85 hundredths, and round that product **up** to the next whole guest to obtain the attrition floor; the `billed_headcount` is then the larger of the attrition floor and the element's `actual_headcount`. On a `CANCELLATION_PENALTY` line the `billed_headcount` is 0, because a cancelled element is not billed by the head. This is deliberately different from the **estimate** variant used before execution, which takes simply the larger of the element's `planned_headcount` and its `guaranteed_headcount` and ignores the attrition floor entirely. For one and the same element with a planned count of 110, a guaranteed count of 100 and an actual turnout of 70, the estimate variant yields 110 and the final variant yields 85.

The line amounts follow. On a `DELIVERY` line, `supplier_cost_cents` is the `billed_headcount` multiplied by the element's `per_person_cost_cents`; on a `CANCELLATION_PENALTY` line it is the element's stamped `cancellation_penalty_cents`. The `markup_cents` figure is `supplier_cost_cents` multiplied by the parent programme's `markup_pct`, read at reconcile time, and rounded half up to whole cents — rounded per line, as §2.6 insists, and only summed afterwards. The `client_charge_cents` figure is `supplier_cost_cents` plus `markup_cents`. The `variance_pct` figure, which is what the client's audit desk actually looks at, is computed only on a `DELIVERY` line whose `guaranteed_headcount` is greater than zero: it is the absolute difference between the element's `actual_headcount` and its `guaranteed_headcount`, divided by the `guaranteed_headcount`, kept to four decimal places and rounded half up. On a `CANCELLATION_PENALTY` line, or where the guaranteed count is zero, `variance_pct` is 0.

While a line is still in `DRAFT`, a `ProgramDirector` may patch it, supplying a `variance_reason` explanation, or a corrected `actual_headcount`, or both. When `actual_headcount` is supplied, the final head-count rule and the line-amount rule are re-run from scratch, rewriting `billed_headcount`, `supplier_cost_cents`, `markup_cents`, `client_charge_cents` and `variance_pct`. Patching increments the line's `version`, and it requires the programme's `settlement_status` to be `RECONCILING`, otherwise `ERR_PROGRAM_NOT_RECONCILING`. Because a patch is not a state transition, that reconciliation-window requirement is evaluated ahead of the line's own `DRAFT` requirement: a patch attempted while the programme has left `RECONCILING` reports `ERR_PROGRAM_NOT_RECONCILING` whatever status the line itself is in, and a patch of an already-`APPROVED` line inside the window reports `ERR_INVALID_STATE_TRANSITION`.

Approving a line advances it `DRAFT` → `APPROVED` and is what admits its figures into the programme's totals. The programme's `settlement_status` must be `RECONCILING`, otherwise `ERR_PROGRAM_NOT_RECONCILING`. And the DMC's variance-tolerance policy applies: a line whose `variance_pct` exceeds 10 hundredths may only be approved if `variance_reason` is present and non-empty, with the unexplained case refused as `ERR_VARIANCE_REASON_REQUIRED`; a line at or below the tolerance needs no explanation. Approval recomputes four programme figures — `final_subtotal_cents` as the sum of `supplier_cost_cents` over the programme's `APPROVED` lines, `disclosed_markup_cents` as the sum of `markup_cents` over the same set, `supplier_gross_payable_cents` (which equals `final_subtotal_cents`, being the gross owed across all suppliers), and `supplier_open_payable_cents` as `supplier_gross_payable_cents` less `supplier_settled_cents` — and increments the line's `version`. A line has no terminal state: `APPROVED` can return to `DRAFT`, as §3.9 describes.

### 3.9. Client Billing, Credit Notes and Supplier Settlement

Issuing the client invoice advances `settlement_status` from `RECONCILING` to `CLIENT_INVOICED` and is a `Controller` action. Two conditions gate it: `settlement_status` must be `RECONCILING`, otherwise `ERR_PROGRAM_NOT_RECONCILING`; and every reconciliation line of the programme must already be `APPROVED`, with any line still in `DRAFT` blocking the invoice as `ERR_RECONCILIATION_LINES_PENDING`. On success the **final** variant of the client-total rule runs, writing `final_subtotal_cents`, `disclosed_markup_cents`, `management_fee_cents` and `final_client_total_cents`; `invoice_issued_at` is stamped with the logical clock instant; and the programme's `version` increments.

The client-total rule is a six-step waterfall whose evaluation order is pinned, because the management fee is both a component of the total and tiered on a base that excludes itself — without the pin the definition is circular. Step one sums the supplier cost across the input set to give the subtotal. Step two sums the markup across the same input set to give the markup total. Step three adds those two to give the **base**. Step four selects the fee rate from the base and from the base alone, never from the grand total: a base below 500,000 cents — that is, below 5,000.00 in the billing currency — attracts a fee of 12 hundredths; a base below 2,000,000 cents (20,000.00) attracts 9 hundredths; and any larger base attracts 7 hundredths. The tier comparisons are strictly less-than against the ceilings, so a base of exactly 500,000 cents falls into the middle band at 9 hundredths and a base of exactly 2,000,000 cents falls into the top band at 7 hundredths. Step five multiplies the base by the selected fee rate and rounds half up to whole cents to give the management fee. Step six adds the base and the management fee to give the total.

The two variants differ only in what they read. The **estimate** variant, run when the programme is confirmed, walks the programme's elements in `PLANNED` or `READY` — no element can be `PERMIT_BLOCKED` at that point, and cancelled, weather-switched and delivered elements are excluded — and for each derives a supplier cost as the estimate billable head count multiplied by that element's `per_person_cost_cents`, plus a markup as that cost multiplied by the programme's `markup_pct` rounded half up per element, summing only after each element has been rounded. Its result is written to `estimated_client_total_cents` alone; it writes nothing to `final_subtotal_cents`, `disclosed_markup_cents` or `management_fee_cents`. The **final** variant, run at invoice issue, walks the programme's reconciliation lines in `APPROVED` status and uses each line's stored `supplier_cost_cents` and `markup_cents` figures. Because it reads lines rather than elements, the final variant includes `CANCELLATION_PENALTY` lines that the estimate variant could not possibly have seen.

The markup-transparency read the client is entitled to see exposes, for one programme, its `program_id`, the frozen `estimated_client_total_cents`, and then the final picture: `final_subtotal_cents`, `disclosed_markup_cents`, `management_fee_cents`, the `fee_pct_applied` rate actually selected by the tier test, `final_client_total_cents`, and the three supplier-side figures `supplier_gross_payable_cents`, `supplier_settled_cents` and `supplier_open_payable_cents`. That read is restricted to a `ProgramDirector` or a `Controller`; the operational roles do not see the fee ladder.

An issued invoice can be taken back. Crediting advances `settlement_status` from `CLIENT_INVOICED` to `CREDITED`, requires a `credit_reason`, and is blocked if any settlement payment of the programme has already reached `PAID`, in which case it is refused with `ERR_SETTLEMENT_ALREADY_PAID`. The credit adds the programme's current `final_client_total_cents` to its cumulative `credit_note_cents` — a credit note is issued for the full invoiced amount — and then reverts every reconciliation line of the programme in `APPROVED` back to `DRAFT`, each such line transition recomputing `final_subtotal_cents`, `disclosed_markup_cents`, `supplier_gross_payable_cents` and `supplier_open_payable_cents` and incrementing the line's own `version`. The programme's `version` increments. Then, within the same request, a further server-driven transition fires: once no reconciliation line of the programme remains `APPROVED`, the programme advances `CREDITED` → `RECONCILING`, setting `management_fee_cents` to 0, `final_client_total_cents` to 0 and `invoice_issued_at` back to null, and incrementing the programme's `version` again. The settlement dimension therefore has a genuine revert cycle: `RECONCILING` → `CLIENT_INVOICED` → `CREDITED` → `RECONCILING`, and the lines it contains have theirs: `DRAFT` → `APPROVED` → `DRAFT`.

Paying the suppliers is the other half of settlement. A `Controller` opens a **settlement payment** by supplying the `program_id`, the `supplier_id` of the payee, the `contract_id` of the contract being discharged, and the `expected_contract_version` guard of §2.5. The payment lands in `PENDING` with `approved_by_user_id` and `released_by_user_id` null, and its four money figures are computed at creation by the deposit-waterfall rule. `gross_cents` is the sum of `supplier_cost_cents` over the reconciliation lines of this programme and this supplier whose status is `APPROVED`. The deposit already banked at countersignature is then consumed against those lines in a fixed order: `CANCELLATION_PENALTY` lines first, then `DELIVERY` lines, and within each group by the underlying element's `starts_at` ascending with `created_at` ascending as the tie-break. Starting from the contract's `deposit_paid_cents` as the remaining deposit, each line in turn absorbs the smaller of the remaining deposit and that line's own `supplier_cost_cents`, and the remaining deposit falls by what it absorbed. `deposit_applied_cents` is the contract's `deposit_paid_cents` less whatever deposit remains at the end of the walk; `net_payable_cents` is `gross_cents` less `deposit_applied_cents`, floored at zero so it is never negative; and `overpayment_credit_cents` is the deposit still stranded after the walk — the money the DMC advanced that this supplier's work never earned. No rounding occurs anywhere in the waterfall, since it only redistributes existing whole cents, and as a result `deposit_applied_cents` plus `overpayment_credit_cents` always equals the contract's `deposit_paid_cents` exactly. Opening the payment also increments the parent contract's `version`.

Approving a payment advances it `PENDING` → `APPROVED` and moves money between the programme's two supplier-side buckets. The programme's `settlement_status` must be `RECONCILING` or `CLIENT_INVOICED`, otherwise `ERR_PROGRAM_NOT_RECONCILING`. The contract named by `contract_id` must still be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`. And the payment's `net_payable_cents` may not exceed the programme's `supplier_open_payable_cents`, since the DMC will not commit more than it owes; an over-commitment is refused with `ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE`. On success `approved_by_user_id` is stamped with the acting `X-User-ID`, `supplier_settled_cents` rises by `net_payable_cents`, `supplier_open_payable_cents` falls by the same amount — the two always sum to `supplier_gross_payable_cents` — and the payment's `version` increments.

Releasing funds advances the payment `APPROVED` → `PAID` and is where the segregation-of-duties rule of §2.10 bites: the acting `X-User-ID` must differ from `approved_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`. On success `released_by_user_id` is stamped with the acting `X-User-ID` and the payment's `version` increments. The release is also the trigger for the programme's final bubble-up: if the programme's `settlement_status` is `CLIENT_INVOICED` and its `supplier_open_payable_cents` has reached zero, and at least one settlement payment of the programme is now `PAID`, then the programme advances `CLIENT_INVOICED` → `SETTLED`, every supplier contract of that programme still in `ACTIVE` is closed as described in §3.3, and the programme's `version` increments.

Voiding a payment is available from `PENDING` or `APPROVED`, takes an optional `void_reason`, and exists to restore the money-conservation invariant when a settlement was opened in error. When the prior status was `APPROVED`, the void subtracts `net_payable_cents` from the programme's `supplier_settled_cents` and adds it back to `supplier_open_payable_cents`, returning the two buckets to the sum they had before approval. When the prior status was `PENDING`, no programme money field changes at all, because a pending payment had never committed anything. Either way the payment's `version` increments. Attempting to void a payment that has already reached `PAID` or `VOID` is refused with `ERR_SETTLEMENT_ALREADY_PAID`. `PAID` and `VOID` are the two terminal settlement-payment states.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read, modify or drive a state transition on an existing resource return `200 OK`. In the authorisation column, **All DMC roles** means the five internal roles — `ProgramDirector`, `OperationsCoordinator`, `SupplierManager`, `Controller` and `PermitOfficer` — and **All roles** means those five plus the external `Supplier` role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | All DMC roles |
| POST | `/dmc/programs` | Create a programme shell for an incoming group | ProgramDirector |
| GET | `/dmc/programs/{program_id}` | Read one programme including every computed money and count field | All DMC roles |
| GET | `/dmc/programs` | List programmes with filtering and pagination | All DMC roles |
| GET | `/dmc/programs/{program_id}/cost-summary` | Computed read exposing the markup-transparency breakdown | ProgramDirector, Controller |
| POST | `/dmc/programs/{program_id}/lock-design` | Freeze the element set so permitting and staffing can begin | ProgramDirector |
| POST | `/dmc/programs/{program_id}/unlock-design` | Revert a locked design back to DRAFT | ProgramDirector |
| POST | `/dmc/programs/{program_id}/confirm` | Confirm the programme to the client and freeze the estimate | ProgramDirector |
| POST | `/dmc/programs/{program_id}/start-execution` | Open on-site execution once the group has landed | OperationsCoordinator |
| POST | `/dmc/programs/{program_id}/cancel` | Cancel the whole programme, cascading into elements and transport | ProgramDirector |
| POST | `/dmc/programs/{program_id}/reconcile` | Open reconciliation, materialising one line per delivered or cancelled element | ProgramDirector |
| POST | `/dmc/programs/{program_id}/issue-invoice` | Issue the client invoice with disclosed markup and tiered management fee | Controller |
| POST | `/dmc/programs/{program_id}/credit-invoice` | Credit an issued invoice and reopen reconciliation | Controller |
| POST | `/dmc/venues` | Register a bookable venue with its turnover buffer | ProgramDirector |
| GET | `/dmc/venues/{venue_id}` | Read one venue | All DMC roles |
| GET | `/dmc/venues` | List venues | All DMC roles |
| POST | `/dmc/suppliers` | Add a local supplier to the vendor file with certificate-of-insurance data | SupplierManager |
| PATCH | `/dmc/suppliers/{supplier_id}` | Update a supplier's insurance data or approval posture | SupplierManager |
| GET | `/dmc/suppliers/{supplier_id}` | Read one supplier | All DMC roles |
| GET | `/dmc/suppliers` | List suppliers | All DMC roles |
| POST | `/dmc/supplier-contracts` | Draft a contract binding one supplier to one programme | SupplierManager |
| GET | `/dmc/supplier-contracts/{contract_id}` | Read one contract | All roles |
| GET | `/dmc/supplier-contracts` | List contracts filtered by programme, supplier or status | All roles |
| POST | `/dmc/supplier-contracts/{contract_id}/send` | Send or re-send the contract to the supplier | SupplierManager |
| POST | `/dmc/supplier-contracts/{contract_id}/counter` | Supplier counters the contract value, opening another round | Supplier |
| POST | `/dmc/supplier-contracts/{contract_id}/countersign` | Countersign the contract, activating it and booking the deposit | SupplierManager |
| POST | `/dmc/supplier-contracts/{contract_id}/terminate` | Terminate the contract and cancel the supplier's open elements | SupplierManager |
| POST | `/dmc/program-elements` | Add a curated element to a DRAFT programme | ProgramDirector |
| GET | `/dmc/program-elements/{element_id}` | Read one program element | All DMC roles |
| GET | `/dmc/program-elements` | List elements by programme, supplier, venue, predecessor, rain-plan parent or status | All DMC roles |
| PATCH | `/dmc/program-elements/{element_id}` | Reshape an element while its programme is still DRAFT | ProgramDirector |
| POST | `/dmc/program-elements/{element_id}/mark-ready` | Mark the element production-ready | OperationsCoordinator |
| POST | `/dmc/program-elements/{element_id}/deliver` | Record actual attendance and close out the element on site | OperationsCoordinator |
| POST | `/dmc/program-elements/{element_id}/weather-switch` | Swap a weather-dependent element for its rain plan | OperationsCoordinator |
| POST | `/dmc/program-elements/{element_id}/cancel` | Cancel one element and stamp the contractual cancellation penalty | ProgramDirector |
| POST | `/dmc/permits` | Open a permit application for an element | PermitOfficer |
| GET | `/dmc/permits/{permit_id}` | Read one permit | All DMC roles |
| GET | `/dmc/permits` | List permits filtered by element or status | All DMC roles |
| POST | `/dmc/permits/{permit_id}/submit` | Submit or resubmit the application to the issuing authority | PermitOfficer |
| POST | `/dmc/permits/{permit_id}/record-decision` | Record the authority's decision | PermitOfficer |
| POST | `/dmc/transport-segments` | Schedule a ground movement | OperationsCoordinator |
| GET | `/dmc/transport-segments/{segment_id}` | Read one transport segment | All DMC roles |
| GET | `/dmc/transport-segments` | List transport segments filtered by programme or status | All DMC roles |
| POST | `/dmc/transport-segments/{segment_id}/depart` | Depart the vehicle, no-showing any guest who never checked in | OperationsCoordinator |
| POST | `/dmc/transport-segments/{segment_id}/cancel` | Cancel a scheduled movement and release its manifest | OperationsCoordinator |
| POST | `/dmc/manifest-entries` | Manifest a guest onto a transport segment | OperationsCoordinator |
| GET | `/dmc/manifest-entries/{manifest_entry_id}` | Read one manifest entry | All DMC roles |
| GET | `/dmc/manifest-entries` | List manifest entries filtered by segment or status | All DMC roles |
| POST | `/dmc/manifest-entries/{manifest_entry_id}/move` | Move a guest to another scheduled segment of the same programme | OperationsCoordinator |
| POST | `/dmc/manifest-entries/{manifest_entry_id}/check-in` | Check a guest in at the curb | OperationsCoordinator |
| POST | `/dmc/staff-members` | Register a coordinator, greeter or activity lead with credential expiries | ProgramDirector |
| PATCH | `/dmc/staff-members/{staff_member_id}` | Update credentials, rate, rest and daily limits, or employment posture | ProgramDirector |
| GET | `/dmc/staff-members/{staff_member_id}` | Read one staff member with credential status derived at the logical clock | All DMC roles |
| GET | `/dmc/staff-members` | List staff members by role, employment posture or derived credential status | All DMC roles |
| POST | `/dmc/staff-assignments` | Propose a shift against either an element or a transport segment | ProgramDirector |
| GET | `/dmc/staff-assignments/{staff_assignment_id}` | Read one staff assignment | All DMC roles |
| GET | `/dmc/staff-assignments` | List staff assignments by member, programme, element, segment or status | All DMC roles |
| POST | `/dmc/staff-assignments/{staff_assignment_id}/confirm` | Confirm the shift after credential, overlap, rest-gap and daily-limit checks | ProgramDirector |
| POST | `/dmc/staff-assignments/{staff_assignment_id}/check-in` | The assigned staff member checks in on site | OperationsCoordinator |
| POST | `/dmc/staff-assignments/{staff_assignment_id}/release` | Release a proposed or confirmed shift | ProgramDirector |
| GET | `/dmc/reconciliation-lines/{reconciliation_line_id}` | Read one reconciliation line | All DMC roles |
| GET | `/dmc/reconciliation-lines` | List reconciliation lines by programme, element, supplier or status | All DMC roles |
| PATCH | `/dmc/reconciliation-lines/{reconciliation_line_id}` | Record a variance explanation or correct attendance on a DRAFT line | ProgramDirector |
| POST | `/dmc/reconciliation-lines/{reconciliation_line_id}/approve` | Approve a line into the programme's payable and billable totals | ProgramDirector |
| POST | `/dmc/settlement-payments` | Open a supplier settlement against a contract, applying the deposit waterfall | Controller |
| GET | `/dmc/settlement-payments/{settlement_payment_id}` | Read one settlement payment | ProgramDirector, SupplierManager, Controller |
| GET | `/dmc/settlement-payments` | List settlement payments by programme, supplier, contract or status | ProgramDirector, SupplierManager, Controller |
| POST | `/dmc/settlement-payments/{settlement_payment_id}/approve` | Approve the settlement, moving the amount from open payable to settled | Controller |
| POST | `/dmc/settlement-payments/{settlement_payment_id}/release` | Release funds to the supplier | Controller |
| POST | `/dmc/settlement-payments/{settlement_payment_id}/void` | Void a pending or approved settlement, restoring the open payable | Controller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_SUPPLIER_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_ELEMENT_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_SEGMENT_NOT_FOUND` | 404 |
| `ERR_MANIFEST_ENTRY_NOT_FOUND` | 404 |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 |
| `ERR_STAFF_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_RECONCILIATION_LINE_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_PAYMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_PROGRAM_DESIGN_LOCKED` | 409 |
| `ERR_PROGRAM_ALREADY_RECONCILING` | 409 |
| `ERR_PROGRAM_NOT_EXECUTION_FINAL` | 409 |
| `ERR_PROGRAM_NOT_RECONCILING` | 409 |
| `ERR_PROGRAM_NOT_CONFIRMED` | 409 |
| `ERR_PROGRAM_NOT_IN_EXECUTION` | 409 |
| `ERR_PROGRAM_WINDOW_NOT_OPEN` | 409 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_SUPPLIER_CONTRACT` | 409 |
| `ERR_PREDECESSOR_NOT_DELIVERED` | 409 |
| `ERR_NO_WEATHER_ALTERNATIVE` | 409 |
| `ERR_ELEMENT_NOT_WEATHER_DEPENDENT` | 409 |
| `ERR_RECONCILIATION_LINES_PENDING` | 409 |
| `ERR_PROGRAM_ALREADY_STAFFED_ON_SITE` | 409 |
| `ERR_SETTLEMENT_ALREADY_PAID` | 409 |
| `ERR_EMPTY_MANIFEST` | 409 |
| `ERR_CHECKIN_WINDOW_NOT_OPEN` | 409 |
| `ERR_SEGMENT_NOT_DUE` | 409 |
| `ERR_ELEMENT_NOT_STARTED` | 409 |
| `ERR_VENUE_TURNOVER_CONFLICT` | 409 |
| `ERR_STAFF_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_STAFF_REST_GAP_VIOLATION` | 409 |
| `ERR_SEGMENT_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_MANIFEST_ENTRY` | 409 |
| `ERR_SUPPLIER_INSURANCE_INSUFFICIENT` | 422 |
| `ERR_SUPPLIER_NOT_APPROVED` | 422 |
| `ERR_CREDENTIAL_EXPIRED` | 422 |
| `ERR_STAFF_INACTIVE` | 422 |
| `ERR_ACCESSIBILITY_UNMET` | 422 |
| `ERR_PERMIT_LEAD_TIME_INSUFFICIENT` | 422 |
| `ERR_STAFF_DAILY_LIMIT_EXCEEDED` | 422 |
| `ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW` | 422 |
| `ERR_ELEMENT_DEPENDENCY_CYCLE` | 422 |
| `ERR_INVALID_WEATHER_ALTERNATIVE` | 422 |
| `ERR_VENUE_CAPACITY_EXCEEDED` | 422 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 422 |
| `ERR_SEGMENT_PROGRAM_MISMATCH` | 422 |
| `ERR_STAFF_ROLE_MISMATCH` | 422 |
| `ERR_PROGRAM_HAS_NO_ELEMENTS` | 422 |
| `ERR_NO_RECONCILABLE_ELEMENTS` | 422 |
| `ERR_MARKUP_PCT_OUT_OF_BAND` | 422 |
| `ERR_VARIANCE_REASON_REQUIRED` | 422 |
| `ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE` | 422 |

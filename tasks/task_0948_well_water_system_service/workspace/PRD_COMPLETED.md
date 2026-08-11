# Well & Water-System Service API — Product Requirements Document

## 1. Introduction

Households that draw their water from a private well have no utility to call. When the pressure tank stops holding, when a lab flags coliform, or when the taps simply run dry on a Sunday night, the only party standing between the family and a dry house is a small field-service company juggling drilling permits, pump inventory, licensed technicians and a lab courier. This document specifies the API for such a company: a service platform that carries a well from its first profile through inspection, water testing, treatment, quoted repair work, emergency no-water dispatch, permit coordination, recurring maintenance, warranty callbacks and, finally, billing.

The platform is built around two structurally different pipelines that share one costing ladder. The **scheduled pipeline** is the deliberate one: a technician inspects the well, an estimator builds and prices a quote, the customer approves it, the jurisdiction issues a permit, a work order is booked into a calendar, and an invoice follows. Authorisation happens *before* the work order exists, and permit approval is a hard prerequisite of scheduling. The **emergency pipeline** inverts both of those orderings: a no-water call is triaged, dispatched and diagnosed on site, and only then — and only when the on-site estimate exceeds the account's pre-authorisation ceiling — does the customer get asked to authorise the money. Emergency work runs permit-exempt, with a post-hoc filing obligation that survives the visit. Labour rates, parts markup, scheduling capacity, warranty attachment and invoice construction are computed identically on both pipelines; dispatch surcharges, authorisation order and permit prerequisites are where they genuinely diverge.

Two properties of the domain drive most of the complexity in the sections that follow. First, almost every number in this system is *derived* rather than entered: a duty-cycle ratio falls out of a pressure-tank drawdown, a maintenance interval falls out of the duty-cycle class, a softener size falls out of a hardness reading and a household count, and a change to any of them propagates retroactively into plans that already exist. Second, the water-quality axis is a regulated one — a presumptive bacteriological finding is *not* a result, it is a question that stays open until a second officer answers it or the retest window lapses — and the system must record the regulator's truth even when the answer is one the requesting endpoint cannot accept. Implementers should read Section 2 as a contract and Section 3 as the domain narrative that gives that contract meaning.

---

## 2. Global Specifications & System-Wide Principles

The whole API is mounted under the path prefix `/water-service`. Everything in this section applies to every endpoint unless a later section explicitly narrows it.

### 2.1. Actors, Identity Headers and Role-Based Access Control

Every request — without exception, including reads — must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` names the role it is acting in. If either header is absent, or if `X-User-Role` is not one of the seven role names below spelled exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted on the addressed endpoint, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`, `ComplianceOfficer`, `BillingClerk` and `CustomerContact`.

- A `PlatformAdmin` is the operator with configuration authority: accounts, properties, wells, technicians, the parts catalog, maintenance plans, the logical clock and coverage voids. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- A `Dispatcher` schedules field work — inspections, emergency triage and dispatch, work-order creation, scheduling and cancellation, and remedy work orders. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- An `Estimator` builds, prices and sends quotes and raises the permits they depend on. When `X-User-Role` is `Estimator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.
- A `ComplianceOfficer` is the water-quality and permitting authority: it records laboratory and confirmatory results and drives the permit lifecycle. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It *is* recorded — as `recorded_by_user_id` and `confirmed_by_user_id` on a `WaterTest` — and those two recorded values are compared against each other by the segregation-of-duties rule in Section 2.13, but neither is ever resolved against a stored entity's `id`.
- A `BillingClerk` is the money authority: it issues invoices, records payments, voids invoices, writes off cancelled work and maintains shared-well splits. When `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- A `Technician` is a field worker. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` row; ownership checks on any resource that references a technician compare the resource's technician foreign key to `X-User-ID`. Concretely, the compared fields are `WorkOrder.assigned_technician_id`, `Inspection.technician_id` and `EmergencyTicket.assigned_technician_id`. A `Technician` that is recorded as `adjudicated_by_user_id` on a callback claim is likewise identified by its `Technician.id`.
- A `CustomerContact` is the account holder acting on its own resources. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an account compare the resource's owning account to `X-User-ID`, resolved through the declared foreign-key chain: an account — and the invoice list read beneath it — directly by its own `id`; an invoice through its `account_id`; a quote through its `property_id` to that property's `account_id`; an emergency ticket through its `account_id`; a work order through its `property_id` to that property's `account_id`; and a treatment recommendation through its `well_profile_id` to that well's `property_id` and on to that property's `account_id`.

An ownership failure by either entity-backed role — a `CustomerContact` whose `X-User-ID` is not the owning account, or a `Technician` whose `X-User-ID` is not the assigned technician — is answered with `ERR_ACTOR_SCOPE_VIOLATION` (HTTP 403).

Ownership is checked **only** on the endpoints whose gate list in Section 4 includes the scope gate. Several read endpoints admit `CustomerContact` without an ownership check — reading a well profile, a water test, a treatment recommendation, a warranty coverage, a callback claim, a maintenance plan, a maintenance visit, a quote line, an invoice line or a shared-well agreement by id — and on those endpoints any authenticated `CustomerContact` may read any row. This is deliberate; do not add an ownership check where Section 4 does not name one.

Three duties are split across roles so that no single principal can complete them alone. An `Estimator` may price and send a quote but may never approve it — approval belongs exclusively to a `CustomerContact` acting on its own account, and an `Estimator` attempting it is refused at the role gate with `ERR_UNAUTHORIZED`. The other two splits are enforced deeper, in Section 2.13.

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

### 2.3. Pagination and List Ordering

Every list endpoint accepts two optional query parameters. `limit` defaults to 10 when omitted, and must be an integer of at least 1 and at most 100. `offset` defaults to 0 when omitted, and must be an integer of at least 0; there is no upper bound on `offset`. A `limit` of 0, a `limit` above 100, a negative `offset`, or a value of either that is not an integer is rejected with `ERR_INVALID_PAGINATION` (HTTP 400). A parameter supplied with an empty value is treated exactly as omitted and takes its default; surrounding whitespace and a leading `+` are tolerated on an otherwise well-formed integer.

The page is the slice of the filtered, sorted row set beginning at `offset` and running for at most `limit` rows. The `meta` block of a list response carries `limit` and `offset` as they were actually applied (after defaulting), `total_count` as the number of rows matching the filters *before* the slice is taken, and `has_more`, which is true exactly when the sum of `offset` and `limit` is strictly less than `total_count`.

Unless an endpoint explicitly says otherwise, every list is sorted by `created_at` ascending — oldest first. The one endpoint that departs from this is the read of an invoice's constructed lines, which is ordered by `sequence_no` ascending. Because the logical clock stamps many rows with the identical instant, rows that share a `created_at` are ordered among themselves by creation sequence — the row created earlier in the run comes first — and that same tie-break applies wherever a later section orders a set by `created_at`.

List endpoints also accept the optional filter parameters named for them in Section 4. A filter parameter is an exact-match filter on the named field. Filter values on read endpoints are **not** enum-validated: a filter carrying a value outside the field's declared member set is not an error, it simply matches no rows and yields an empty page with `total_count` 0. The comparison is made against the row's stored value rendered as a string, with two conventions: a boolean field matches the case-insensitive words `true` and `false`, and a row whose value for the filtered field is null matches only the literal `null`. A filter parameter that is omitted altogether narrows nothing.

### 2.4. The Logical Clock and the Rendering of Instants

The server runs on a **logical clock**, not on wall-clock time. On server start the clock reads exactly `2026-05-01T00:00:00Z` and it must never fall back to real time. A `PlatformAdmin` advances it by supplying a `to_iso8601` instant to the clock-advance capability; the response reports `current_utc` and `previous_utc`. The clock may move forward or stay where it is, but never backwards: a `to_iso8601` strictly before the current clock is rejected with `ERR_CLOCK_BACKWARD` (HTTP 400), and a `to_iso8601` that is not a parseable ISO 8601 UTC instant is rejected with `ERR_INVALID_TIMESTAMP` (HTTP 400). Every instant the server *stamps* — `created_at`, `updated_at`, `completed_at`, `sent_at`, `approved_at`, `intake_at`, `dispatched_at`, `actual_start_at`, `actual_end_at`, `posted_at`, `filed_at`, `issued_at`, `submitted_at`, `overdue_latched_at`, `performed_at`, `starts_at`, `last_service_date`, `last_filter_change_date`, `last_salt_delivery_date` — is read from this logical clock, never from the host's real clock.

**Rendering is pinned once, here, and applies to every instant in every response body.** An instant is rendered as an ISO 8601 UTC string with exactly four-digit year, two-digit month and day separated by hyphens, the literal `T`, two-digit hour, minute and second separated by colons, a decimal point, exactly **three** fractional-second digits, and the literal suffix `Z` — for example `2026-05-01T00:00:00.000Z`. There is never a `+00:00` offset form, never a missing fractional part, and never more or fewer than three fractional digits. A null instant is rendered as JSON `null`.

**A timestamp supplied by the client is re-rendered in that canonical form on the way out; it is never echoed back byte-for-byte as the client sent it.** If a client posts a `sample_datetime` of `2026-05-02T09:00:00Z`, every later response that carries that field renders it `2026-05-02T09:00:00.000Z`. If a client posts `2026-05-02T09:00:00.123456Z`, the stored instant keeps its sub-millisecond precision for arithmetic but renders as `2026-05-02T09:00:00.123Z`. Two instants are compared as instants, never as strings.

Client-supplied instants are accepted in any parseable ISO 8601 UTC form. A body field declared as a datetime that does not parse is rejected with `ERR_INVALID_TIMESTAMP`. Reduced precision (`2026-06-01T12:00Z`), a comma in place of the decimal point, and a numeric UTC offset such as `2026-06-01T14:00+02:00` are all parseable forms. Two things are **not**, because a string missing either one does not denote a UTC instant at all: the literal `T` date/time separator, and a zone designator. A string such as `2026-06-01 12:00`, which lacks both, is `ERR_INVALID_TIMESTAMP`. One parser serves every datetime body field on every endpoint, so these rules are identical everywhere.

### 2.5. Common Resource Properties and `version` Semantics

Every persisted resource carries an `id`, which is a server-minted UUID string with no type prefix and no client control over its value, and a `created_at` instant stamped from the logical clock at creation.

Nineteen of the twenty-one entity kinds additionally carry `updated_at` — an instant refreshed from the logical clock on every mutation of that row — and `version`, an integer that starts at 1 when the row is created. The two exceptions are `MaintenanceVisit` and `InvoiceLine`: those two carry **only** `id` and `created_at`. They have no `updated_at` and no `version` field at all, and neither field appears in their JSON representation.

`version` increments by exactly **one per entity per successful request**, not once per mutation step and not once per cascade hop. A single work-order completion touches the work order, several maintenance plans, the well profile, an emergency ticket and possibly a callback claim and a warranty coverage; each of those rows sees its `version` rise by exactly 1, however many hops of the cascade wrote to it. `updated_at` is refreshed on the same rows in the same way.

**The bump is part of the mutation itself, not a step that happens after the response has been composed.** Every response body renders the **post-mutation** state of every row it carries: the `version` a mutating call returns is the already-raised one and the `updated_at` it returns is the already-refreshed one, never the values the row held when the request arrived. A client may therefore take the `version` it has just been handed back and echo it straight into the next `expected_<parent>_version` field of Section 2.8 without re-reading the row. This holds on every entity kind that carries a `version`, and it holds for the rows written by the three mutate-then-reject rungs of Section 2.11 too: those responses carry an error body rather than an entity, but the rows they wrote are readable afterwards at their raised `version`.

Every field named on an entity in Section 3 is part of that entity's JSON representation and is response-visible, including the computed ones (`service_zone`, `duty_cycle_ratio`, `duty_cycle_class`, `status_effective`, `coverage_state`, `hold_time_valid`, `response_minutes`, `preauth_cap_cents`, `days_since_coverage_start`, `billable_minutes`, `callback_attempt_count`, `shared_split_pct` and the rest). A computed field whose inputs are not yet available renders as `null`. Named quantities that appear only *inside* a calculation — the pre-discount pre-tax figure, the daily grain load, a per-share raw amount before the remainder is placed — are intermediates and are not response-visible.

Nested reads validate their path parameters left to right. A request addressing a plan's visits validates the plan first; the leftmost unresolved identifier is the one whose error is returned.

### 2.6. The Nine-Gate Global Write Order

Every mutating endpoint evaluates its checks in one **global, total order** of nine gates. This ordering is not advisory and it is not per-endpoint: it is the same everywhere, and each endpoint simply runs the subset of gates that applies to it, always in this sequence.

1. **G1 — Authentication.** `X-User-Role` is present and is one of the seven declared roles, and `X-User-ID` is present. Failure: `ERR_UNAUTHENTICATED`.
2. **G2 — Role.** The declared role appears in the endpoint's authorised-role list. Failure: `ERR_UNAUTHORIZED`.
3. **G3 — Path existence.** Every `{id}` segment in the request *path* resolves to a stored row, validated left to right. Failure: the `*_NOT_FOUND` error of the entity that failed.
4. **G4 — Actor scope.** Ownership and assignment for the two entity-backed roles, as described in Section 2.1. Failure: `ERR_ACTOR_SCOPE_VIOLATION`.
5. **G5 — Entity state.** The addressed row's stored state satisfies the requested transition's originating state, **on every axis the transition touches**. Failure: that entity's invalid-state error.
6. **G6 — Regulatory.** Permit, water-quality and segregation-of-duties preconditions imposed by the jurisdiction or the compliance programme.
7. **G7 — Optimistic concurrency.** The `expected_<parent>_version` field in the body equals the stored parent's `version`.
8. **G8 — Payload.** Presence, JSON type, enum membership, numeric range and timestamp format of every body field. Its sub-gate **G8_QUERY** validates pagination query parameters on read endpoints. Foreign keys named in the *body* are **not** resolved here — only their syntactic shape is checked.
9. **G9 — Business.** Sub-gate **G9A** resolves body-referenced foreign keys; a body field naming a row that does not exist fails *here*, with that entity's `*_NOT_FOUND` error, and never at G3. Where an endpoint names several body foreign keys, G9A resolves them in the order that endpoint's request list in Section 4 declares them, and the leftmost one that does not resolve is the one whose error is returned. Sub-gate **G9B** then runs cross-entity business rules in this fixed internal order: safety and potability first, then capacity and temporal overlap, then quantity and stock, then fiscal rules (credit hold, payment, caps).

**A request that violates several gates is answered with the error of the lowest-numbered gate it violates, and no later gate is evaluated.** A `CustomerContact` presenting a malformed body against a resource it does not own gets `ERR_ACTOR_SCOPE_VIOLATION` (G4), not a payload error (G8). A stale `expected_quote_version` accompanying an out-of-range `quantity` gets `ERR_STALE_QUOTE_VERSION` (G7), because concurrency is checked before payload. A request against a row in the wrong state with an unknown role gets `ERR_UNAUTHORIZED` (G2), because the role gate precedes the state gate.

**The existence errors, one per entity kind.** Each identifier — whether it arrives as a path segment at G3 or as a body field at G9A — has exactly one error that answers a value which does not resolve to a stored row, and all of them are HTTP 404. An unresolved `account_id` is `ERR_ACCOUNT_NOT_FOUND`. An unresolved `property_id` is `ERR_PROPERTY_NOT_FOUND`. An unresolved `well_profile_id` is `ERR_WELL_PROFILE_NOT_FOUND`. An unresolved `shared_well_agreement_id` is `ERR_SHARED_WELL_AGREEMENT_NOT_FOUND`. An unresolved `technician_id`, `collected_by_technician_id` or `assigned_technician_id` is `ERR_TECHNICIAN_NOT_FOUND`. An unresolved `part_catalog_item_id`, including a `mandated_alternate_part_id`, is `ERR_PART_CATALOG_ITEM_NOT_FOUND`. An unresolved `inspection_id` is `ERR_INSPECTION_NOT_FOUND`. An unresolved `water_test_id` is `ERR_WATER_TEST_NOT_FOUND`. An unresolved `treatment_recommendation_id` is `ERR_TREATMENT_RECOMMENDATION_NOT_FOUND`. An unresolved `quote_id` is `ERR_QUOTE_NOT_FOUND`. An unresolved `quote_line_id` or `superseded_quote_line_id` is `ERR_QUOTE_LINE_NOT_FOUND`. An unresolved `work_order_id` is `ERR_WORK_ORDER_NOT_FOUND`. An unresolved `emergency_ticket_id` is `ERR_EMERGENCY_TICKET_NOT_FOUND`. An unresolved `permit_id` is `ERR_PERMIT_NOT_FOUND`. An unresolved `parts_consumption_entry_id` is `ERR_PARTS_CONSUMPTION_ENTRY_NOT_FOUND`. An unresolved `warranty_coverage_id` is `ERR_WARRANTY_COVERAGE_NOT_FOUND`. An unresolved `callback_claim_id` is `ERR_CALLBACK_CLAIM_NOT_FOUND`. An unresolved `maintenance_plan_id` is `ERR_MAINTENANCE_PLAN_NOT_FOUND`. An unresolved `maintenance_visit_id` is `ERR_MAINTENANCE_VISIT_NOT_FOUND`. An unresolved `invoice_id` is `ERR_INVOICE_NOT_FOUND`. An unresolved `invoice_line_id` is `ERR_INVOICE_LINE_NOT_FOUND`.

Read-only endpoints run G1, G2, G3, G4 and G8_QUERY only, in that order. They never run G5, G6, G7, G9 or the body half of G8.

**A gate that runs before G8 and needs to read a body field reads it non-fatally.** Such a gate never rejects a request because the field it wanted is missing or unusable: when the value cannot be used — a datetime that does not parse, an enum value that is not a declared member — the individual check that needed it is **skipped**, so that G8 still gets to answer with `ERR_INVALID_TIMESTAMP` or `ERR_INVALID_ENUM`. Three places rely on this. **G7 itself** reads its `expected_<parent>_version` field this way: when that field is absent, or is present but is not a JSON integer, the concurrency comparison is skipped entirely and G8 answers with `ERR_VALIDATION` for the missing or mistyped required field rather than G7 answering with a stale-version error — so "a stale version beats a malformed body" holds only for a version that is itself a well-formed integer. The confirmatory retest's G6 window checks skip when `confirm_sample_datetime` or `confirm_analyzed_at` fails to parse — each check independently, so a parseable `confirm_sample_datetime` still gets its retest-window test even when `confirm_analyzed_at` is unusable — while the segregation-of-duties check on the same gate reads no body field and therefore always runs. And the callback adjudication's G5 state gate, whose permitted originating state depends on the `decision` in the body, admits **any** adjudicable state — `SUBMITTED` or `UNDER_REVIEW` — when `decision` is not one of the three declared members.

Within a single gate, checks are evaluated in the order the sections below give them, and **that narrative order is the governing one**. Where the Section 3 workflow that owns a transition names the checks of a gate in a sequence, that sequence *is* the intra-gate precedence. It outranks the coarse category sequence just given for G9B — safety, then capacity, then quantity and stock, then fiscal — which sketches the general shape of the ordering and never overrides an explicit narrative. It also outranks the order of the per-endpoint error lists of Section 4: **such a list is a membership list of the errors that endpoint can return, never a precedence order, and nothing may be inferred from the order in which its entries happen to appear.** Two orderings inside G5 deserve naming now because they are otherwise guessable in two ways. On write-off, the **billing** axis is checked *before* the fulfilment axis: a work order whose billing axis is not `NOT_BILLABLE` is refused with `ERR_WORK_ORDER_INVALID_BILLING_STATE` even if its fulfilment axis is also wrong, and only once the billing axis passes is `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE` raised for a fulfilment axis that is not `CANCELLED`. On a duplicate shared-well agreement that would *also* break the share sum, the duplicate check runs first, so the answer is `ERR_DUPLICATE_SHARED_WELL_AGREEMENT`, not `ERR_SHARED_WELL_SPLIT_INVALID`.

### 2.7. Payload Validation and the Closed Routing of Enum Errors

At G8 the server checks that every required body field is present and carries the declared JSON type. A missing required field, or one of the wrong JSON type, is `ERR_VALIDATION` (HTTP 400). Body fields the endpoint does not declare are ignored silently — an unknown key is never an error.

**G8 itself runs as five passes, each completing over every declared field before the next begins**: presence and JSON type first; then enum membership; then timestamp format; then the strictly-negative-quantity test; then the remaining value constraints — string value sets such as the jurisdiction codes, numeric minima and maxima, string lengths, and the at-sign test on an email. Within a pass the fields are examined in the order the endpoint's request list in Section 4 declares them. So a required field missing anywhere in the body beats a bad enum member elsewhere in it, a bad enum member beats an unparseable timestamp, and a strictly negative quantity beats an out-of-range value. An explicit JSON `null` supplied for an **optional** field is treated exactly as if the field had been omitted, and that field's stated default applies; an explicit `null` supplied for a **required** field is `ERR_VALIDATION`. A request body that is not valid JSON, or that is valid JSON but is not an object, is likewise `ERR_VALIDATION`; an absent body is read as the empty object.

`ERR_INVALID_ENUM` (HTTP 400) is reserved for enum-typed **body** fields on **mutating** endpoints, and the set of fields that route to it is closed. A body field routes to `ERR_INVALID_ENUM` **if and only if** it is one of the following:

- `membership_tier` — on account creation and on the account membership-tier change. Members: `NONE`, `SELECT`, `PREMIER`.
- `well_type` — on well-profile creation. Members: `DRILLED`, `DRIVEN`, `DUG`.
- `tier` — on technician creation. Members: `APPRENTICE`, `JOURNEYMAN`, `MASTER`.
- `status` — on technician creation, on the technician availability change, on catalog-part creation and on the catalog-part change. Members on a technician: `AVAILABLE`, `OFF_DUTY`. Members on a catalog part: `ACTIVE`, `DISCONTINUED`.
- `category` — on catalog-part creation. Members: `PUMP`, `PRESSURE_TANK`, `FILTRATION`, `CONTROL`, `CONSUMABLE`.
- `media_kind` — on catalog-part creation. Members: `NONE`, `SEDIMENT`, `CARBON`, `SOFTENER_RESIN`.
- `panel_type` — on water-sample creation. Members: `BACTERIOLOGICAL`, `CHEMICAL`.
- `scope` — on quote creation, on permit creation, on work-order creation and on remedy-work-order creation. Members on a quote and on a permit: `NEW_WELL`, `PUMP_REPLACEMENT`, `PRESSURE_TANK`, `TREATMENT_INSTALL`, `REPAIR`. Members on a work order and on a remedy work order: those five plus `MAINTENANCE`.
- `quoted_technician_tier` — on quote creation. Members: `APPRENTICE`, `JOURNEYMAN`, `MASTER`.
- `cause_class` — on emergency diagnosis. Members: `PUMP_FAILURE`, `WELL_DRY`, `PRESSURE_TANK_FAILURE`, `CONTROL_FAILURE`, `TREATMENT_FAILURE`, `NON_WELL_CAUSE`.
- `complaint_class` — on callback-claim intake. Members: `PART`, `LABOR`.
- `decision` — on callback-claim adjudication. Members: `REVIEW`, `APPROVE`, `REJECT`.

**No other body field routes to `ERR_INVALID_ENUM`.** In particular, the jurisdiction-code fields — `billing_jurisdiction_code` on an account, `jurisdiction_code` on a property, on a well profile and on a permit, and `home_jurisdiction_code` on a technician — are declared as *strings* constrained to the four codes `JUR_ALPHA`, `JUR_BRAVO`, `JUR_CHARLIE` and `JUR_DELTA`; a value outside that set is a string-constraint failure and is answered with `ERR_VALIDATION`, not `ERR_INVALID_ENUM`. Likewise, filter parameters on read endpoints never produce `ERR_INVALID_ENUM` (see Section 2.3), and no path parameter ever does.

`ERR_INVALID_TIMESTAMP` (HTTP 400) is raised when a datetime **body** field on a mutating endpoint does not parse as an ISO 8601 UTC instant. The closed set of such fields is: `to_iso8601` on the clock advance; `scheduled_for` on inspection creation; `sample_datetime` on water-sample creation; `analyzed_at` on a laboratory result; `confirm_sample_datetime` and `confirm_analyzed_at` on a confirmatory result; `estimated_start_at` on quote creation; and `scheduled_start_at` and `scheduled_end_at` on work-order scheduling. No other field routes here.

`ERR_NEGATIVE_QUANTITY` (HTTP 400) is raised when a quantity, amount or pounds body field is **strictly** negative. Zero passes this gate. The closed set of endpoints and fields is: `quantity` on a parts-consumption posting and on a quote line; `delivered_lbs` on a salt delivery; and `amount_cents` on a payment. A zero payment amount therefore passes G8 and is adjudicated later, at G9, with `ERR_PAYMENT_AMOUNT_INVALID`.

`ERR_INVALID_DATE_RANGE` (HTTP 400) is raised on exactly two endpoints. On work-order scheduling it fires when `scheduled_end_at` is not strictly after `scheduled_start_at`. On a laboratory result it fires when `analyzed_at` precedes `sample_datetime`.

### 2.8. Optimistic Concurrency Control

Four write endpoints carry optimistic concurrency on a parent row's `version`. On each of them the version field is a **required, non-optional** body field, and it is checked at G7 — after the state gate and before payload validation, so a stale version beats a malformed body. Every endpoint not named here takes no version field at all, and supplying one there is simply ignored.

- Creating a treatment recommendation under a well profile requires `expected_well_profile_version` carrying the client's last observed `version` of that `WellProfile`. A mismatch with the stored value is rejected with `ERR_STALE_WELL_PROFILE_VERSION` (HTTP 412). A new recommendation legitimately supersedes the prior one, so a second sequential create would succeed on its own terms; the stale-version check is what stops a writer from superseding a recommendation it never saw — for instance, one authored after a confirmatory retest moved the well to `UNSAFE`.
- Adding a line to a quote requires `expected_quote_version` carrying the client's last observed `version` of that `Quote`. A mismatch is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412). Adding lines is legitimately repeatable, so the check exists to stop an estimator appending to a line set a permit condition has already reshaped.
- Recording a payment against an invoice requires `expected_invoice_version` carrying the client's last observed `version` of that `Invoice`. A mismatch is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412). Part payments are legitimately repeatable, so the check exists to stop a clerk posting against an outstanding amount it never observed.
- Recording a salt delivery against a maintenance plan requires `expected_maintenance_plan_version` carrying the client's last observed `version` of that `MaintenancePlan`. A mismatch is rejected with `ERR_STALE_MAINTENANCE_PLAN_VERSION` (HTTP 412). Deliveries are legitimately repeatable and top up the same brine tank, so the check exists to stop a driver topping up against a remaining-pounds figure it never observed.

### 2.9. Money, Rounding and Evaluation Order

All money is carried in whole cents as integers. Every rounding in this system is **round half up** — a value exactly on the half rounds away from zero — and rounding happens only at the points the calculation narratives name. Two of those orderings are pinned and produce different answers if reordered:

- **Labour is rounded twice.** The hourly rate is rounded to whole cents *first*, and the already-rounded rate is what gets multiplied by minutes divided by sixty and rounded to whole cents a *second* time. Computing base rate times band multiplier times minutes divided by sixty in one expression, with a single rounding at the end, is a different and incorrect result.
- **Parts are rounded per unit, then extended, then summed.** The marked-up price of one unit is rounded to whole cents before it is multiplied by the quantity; the already-rounded line extensions are what get added together. Summing unrounded unit prices and rounding the sum is a different and incorrect result. For example, a part costing 5001 cents at quantity 3 gives a unit price of 7001 cents and an extension of 21003 cents; sum-then-round would give 21004.

Percentages that are not money — a duty-cycle ratio, a share percentage, a monthly salt burn — round to the number of decimal places the owning calculation states: two places for a duty-cycle ratio, two places for a share percentage, one place for a monthly salt figure. Grain figures round to whole integers, minutes to whole minutes, and day counts are floored.

### 2.10. Boundary Conventions for Every Window and Band

Every window and band in this specification states its own inclusive or exclusive endpoints, and the following conventions hold globally.

- **Warranty windows are closed on the right, in whole days.** A claim filed exactly `PART_WARRANTY_DAYS` (365 days) after a part coverage started is *in* warranty; one day later is out. A labour claim filed exactly `LABOR_WARRANTY_DAYS` (90 days) after the coverage started is *in* warranty; 91 days is out. Formally, a coverage is in force when the elapsed whole days from its start instant are at least zero and at most the window.
- **The bacteriological retest window is closed on the right.** A confirmatory sample drawn exactly `RETEST_WINDOW_DAYS` (21 days, that is 1,814,400 seconds) after the original sample is *in* window; one second later is out.
- **Water-test hold time is closed on the right.** An analysis completed exactly at the hold-time limit after sampling is *valid*; one second later is not.
- **Treatment-recommendation validity is half-open.** It runs from the sample instant up to but *not including* the sample instant plus `RECOMMENDATION_VALIDITY_DAYS` (180 days). At exactly the boundary instant the recommendation is already expired.
- **Technician scheduled windows are half-open** — they include their start instant and exclude their end instant — and the candidate window is expanded by `TRAVEL_BUFFER_MINUTES` (45 minutes) on **both** sides before the overlap test, so two windows that merely touch *do* collide.
- **The per-well daily cap buckets a work order into the UTC calendar day of its start instant only.** Both day boundaries belong to that day: `00:00:00.000Z` and `23:59:59.999Z` are the same bucket. A work order that runs across midnight counts only against its start date.
- **Numeric bands state their own endpoints.** Unless a band says otherwise, its upper bound is inclusive: a value sitting exactly on a band's ceiling belongs to that band and not to the next one up.

The named constants used throughout, with their values: `TAX_RATE_PCT` 7.25 percent; `LOYALTY_DISCOUNT_PCT` 5.00 percent; `LOYALTY_DISCOUNT_MIN_PRETAX_CENTS` 200000 cents; `LOYALTY_DISCOUNT_ELIGIBLE_TIERS` the two tiers `SELECT` and `PREMIER`; `CREDIT_HOLD_THRESHOLD_CENTS` 500000 cents; `QUOTE_VALIDITY_DAYS` 30 days; `INSPECTION_VALIDITY_DAYS` 365 days; `PART_WARRANTY_DAYS` 365 days; `LABOR_WARRANTY_DAYS` 90 days; `CALLBACK_MAX_PER_COVERAGE` 2 claims; `TRAVEL_BUFFER_MINUTES` 45 minutes; `WELL_DAILY_WORK_ORDER_CAP` 1 work order; `MAX_WORK_ORDER_DURATION_MINUTES` 720 minutes; `BILLING_INCREMENT_MINUTES` 15 minutes; `MIN_BILLABLE_MINUTES` 60 minutes; `NON_WELL_CAUSE_LABOR_CAP_MINUTES` 60 minutes; `PART_MAX_LINE_QUANTITY` 50 units; `SHARED_WELL_MAX_PARTIES` 4 accounts; `POST_HOC_PERMIT_WINDOW_DAYS` 10 days; `RETEST_WINDOW_DAYS` 21 days; `RECOMMENDATION_VALIDITY_DAYS` 180 days; `SALT_TANK_CAPACITY_LBS` 300 pounds; `SALT_REORDER_THRESHOLD_LBS` 40 pounds; `SALT_DELIVERY_MIN_LBS` 40 pounds; `FILTER_MIN_DAYS_BETWEEN_CHANGES` 30 days; `MIN_MAINTENANCE_INTERVAL_DAYS` 120 days; `YIELD_SAFETY_FACTOR` 0.80; `MIN_PUMP_GPM` 5.0 gallons per minute; `PEAK_DEMAND_GAL_PER_HOUR` 30 gallons per hour; `MIN_DRAWDOWN_GALLONS` 1.0 gallon; `SALT_LBS_PER_CONSUMABLE_UNIT` 40.0 pounds; `HARDNESS_TREATMENT_TRIGGER_GPG` 7.0 grains per gallon; `NITRATE_MCL_MG_L` 10.0 milligrams per litre; `ARSENIC_MCL_MG_L` 0.010 milligrams per litre; `LEAD_MCL_MG_L` 0.015 milligrams per litre; `IRON_MCL_MG_L` 0.30 milligrams per litre; `HOLD_TIME_HOURS_BACTERIOLOGICAL` 30 hours; `HOLD_TIME_HOURS_CHEMICAL` 336 hours; `WATER_USE_GAL_PER_PERSON_PER_DAY` 75 gallons; `REGEN_INTERVAL_DAYS` 7 days; `EXPEDITE_FEE_CENTS` 15000 cents; and `SEVERITY_MAX` 100 points. The logical clock's start value, `DEFAULT_CLOCK_UTC`, is `2026-05-01T00:00:00Z`.

### 2.11. Writes That Persist Behind an Error Response

Three transitions in this system perform a **durable state write and then still return an error**. The write is *not* rolled back, and the rows it produced are readable afterwards through the ordinary list and read endpoints. All three sit at G9 — every gate from G1 through G8 has already passed, the endpoint has committed its recording side effects, and the terminal business adjudication then fails. **If any gate from G1 through G8 fails instead, no write happens at all and that gate's error is what comes back.** An implementation that treats an error response as a rollback signal will get all three of these wrong.

1. **A confirmatory retest that confirms coliform.** The child test row is created, the parent test latches to `CONFIRMED_POSITIVE`, `confirmed_by_user_id` is stored, the well moves to `UNSAFE` with an advisory reason of `CONFIRMED_COLIFORM`, and both `version` counters rise — and only then does the call return `ERR_RETEST_CONFIRMED_POSITIVE` (HTTP 422). The endpoint's contract is "clear the presumptive advisory", and a confirming retest cannot satisfy that contract, yet the durable record of the confirmation is precisely what the regulator requires.
2. **A quote approval whose pump line no longer clears the yield gate.** Every offending line moves to `SUPERSEDED_BY_YIELD`, the quote moves to `REVISION_REQUIRED`, and the quote's and each offending line's `version` rise — and only then does the call return `ERR_QUOTE_LINE_YIELD_EXCEEDED` (HTTP 409).
3. **A callback claim raised against an out-of-window coverage.** The `CallbackClaim` row is created durably with status `REJECTED_OUT_OF_WARRANTY` and `submitted_at` stamped, the coverage's `claim_count` and the work order's `callback_attempt_count` are incremented, the work order's `callback_eligibility` is set to `EXPIRED`, and the work order's and coverage's `version` counters rise — and only then does the call return `ERR_CALLBACK_OUT_OF_WARRANTY` (HTTP 409). The attempt is a compliance record the business is required to keep even though the claim fails.

### 2.12. Two Conserved Quantities

The platform maintains two accounting identities that every forward action and its compensating action must leave exactly satisfied.

**Inventory.** For every catalog part, the sum of its `on_hand_qty` and the quantities of all consumption rows for that part whose status is `POSTED` is invariant across posting and reversal. Posting a consumption row is the forward action: it decrements `on_hand_qty` by the posted quantity at the instant of posting, not at completion. Cancelling an in-progress work order is the compensating action: every `POSTED` row on it moves to `REVERSED` and `on_hand_qty` is restored by exactly that quantity. Work-order completion moves no stock at all — it only freezes prices — so the identity holds across it too. Rows in `REVERSED` never participate in the sum.

**The account ledger.** An account's `balance_cents` equals the sum, over that account's invoices whose status is `ISSUED`, `PARTIALLY_PAID` or `PAID_IN_FULL`, of the invoice's `total_cents` less its `amount_paid_cents`. Invoices in `DRAFT` and `VOID` are excluded. Issuing is the forward action; voiding is the compensating action and removes exactly what issuing and paying added. On every write that touches `balance_cents`, `credit_hold` is re-derived as true when `balance_cents` is **strictly greater** than `CREDIT_HOLD_THRESHOLD_CENTS` (500000 cents) and false otherwise; a balance of exactly 500000 does not put an account on hold.

### 2.13. Segregation of Duties

Two duties beyond the estimator/customer split of Section 2.1 are enforced at G6, and both compare `X-User-ID` against a value recorded earlier on a row.

The `ComplianceOfficer` who recorded a presumptive bacteriological result must **not** be the one who records its confirmatory result. If the `X-User-ID` presenting a confirmatory result equals the test's stored `recorded_by_user_id`, the request is refused with `ERR_CONFIRMATORY_SAME_OFFICER` (HTTP 403), and nothing is written.

The `Technician` assigned to a work order must **not** be the one who adjudicates a callback claim raised against that work order. If the adjudicating `X-User-ID` equals the original work order's `assigned_technician_id`, the request is refused with `ERR_CALLBACK_ADJUDICATOR_CONFLICT` (HTTP 403). This applies to every adjudication decision — review, approve and reject alike.

### 2.14. Tensions Deliberately Left Open

Eleven points in this domain admit two defensible readings. They are recorded here as open questions, not as settled rules, so that nobody mistakes silence for agreement. Where a downstream number would otherwise be undefined, the pinned computational behaviour is stated — but the *interpretive* question stays open.

1. **Re-anchoring of treatment-recommendation expiry after a confirmatory retest.** One reading keeps expiry anchored to the original panel's `sample_datetime`, because the recommendation cites that panel's analytes. The other re-anchors it to the confirmatory retest's sample instant, because the retest supersedes the original panel. Both readings agree that expiry is anchored on a *sample* instant and never on the recommendation's own `created_at`.
2. **Whether a `NON_WELL_CAUSE` resolution also collapses the trip fee to the zone-1 rate.** One reading keeps the property's own zone rate and collapses only the dispatch surcharge. The other treats a non-well cause as not a well service at all and bills the whole visit at the zone-1 flat rate. Both readings agree the *dispatch surcharge* component collapses to zero.
3. **Scope of the shared-well split on an invoice carrying a dispatch surcharge.** One reading splits the entire invoice total, surcharge included, because the well is jointly owned. The other splits only parts and labour and leaves the surcharge with the account that placed the emergency call. Both readings agree that parts and labour are split.
4. **Whether a maintenance-relevant repair performed on an emergency work order clears a plan's overdue latch.** One reading clears the latch only from a maintenance-class work order's visit. The other clears it from any completed work order that resets at least one of the two clocks. Both readings agree that an interval recomputation alone never clears it.
5. **Re-approval after a permit-mandated alternate reduces the quote total.** One reading sends any supersede to `REVISION_REQUIRED` and requires the customer to approve again. The other allows a supersede whose new total is at most the previously approved total to restore `APPROVED` automatically. Both readings agree that a supersede that *raises* the total requires re-approval.
6. **Term of the coverage minted when a part is replaced under warranty.** One reading gives a fresh full-term coverage running from the new consumption date. The other inherits only the remaining term of the coverage it supersedes. Both readings agree that a new coverage is minted and the old one is marked superseded.
7. **Whether inspection staleness is re-checked at work-order scheduling.** One reading treats staleness as a quote-approval concern only. The other treats scheduling as a fresh regulatory moment that must re-check the inspection-validity window. Both readings agree staleness is checked at approval.
8. **Which membership tier governs the dispatch credit when the tier changes mid-ticket.** One reading uses the tier stored on the account at ticket intake; the other uses the tier stored at invoice construction. Both readings agree the ticket records `membership_tier_at_intake` at intake and that changing an account's tier never rewrites that stored value.
9. **Whether a chemical exceedance should hold a well at `ADVISORY` after a bacteriological clearance.** One reading restores `SAFE` outright, treating chemical exceedance as a treatment matter rather than a potability matter. The other holds the well at `ADVISORY` while a chemical exceedance is unresolved. Both readings agree the bacteriological question itself is closed by the clearance.
10. **What `last_service_date` means when a visit touches only the salt clock.** The compliance rule counts only filter-bearing visits, yet `last_service_date` is pinned to advance on a maintenance visit of *any* kind — so a salt-only visit slides `next_due_at` forward while the plan stays `OVERDUE`. That computational behaviour is pinned for determinism and Section 3.10 states it. The naming tension — whether the field should mean "last physical visit" or "last compliance-qualifying service" — is **not** adjudicated here.
11. **Whether the loyalty discount participates in its own eligibility test.** The pre-tax total used for the eligibility threshold is pinned to the **pre-discount** figure, for evaluation-order determinism, and Section 3.11 states it. The commercial reading — that an invoice whose post-discount total falls below the threshold should lose the discount entirely — remains un-adjudicated.

---

## 3. Business Logic & Workflows

### 3.1. The Register: Accounts, Properties, Wells and Shared Ownership

Everything in the platform hangs off an **account**. A `PlatformAdmin` opens one by supplying a `legal_name` of between 1 and 120 characters, a `billing_jurisdiction_code` drawn from `JUR_ALPHA`, `JUR_BRAVO`, `JUR_CHARLIE` and `JUR_DELTA`, a `contact_email` that must contain an at-sign, and optionally a `membership_tier`. When `membership_tier` is omitted it defaults to `NONE`; the other members are `SELECT` and `PREMIER`. A freshly created account starts with `balance_cents` 0, `lifetime_invoiced_cents` 0, `lifetime_paid_cents` 0 and `credit_hold` false. The membership tier is the one mutable attribute: a `PlatformAdmin` may change it later, which bumps the account's `version` by 1 but does **not** retroactively rewrite `membership_tier_at_intake` on any emergency ticket already raised.

A **property** is the physical site. It carries `account_id` naming the account billed for work there, an `address_line`, its own `jurisdiction_code` from the same four codes, a `distance_miles` road distance from the depot which must be at least 0.0, a `household_size` between 1 and 12 inclusive, and `has_vulnerable_occupant`, which defaults to false when omitted. Distance drives the trip-fee zone. Distances up to and including 15.0 miles are `ZONE_1` and carry a trip fee of 8500 cents; above 15.0 and up to and including 35.0 miles is `ZONE_2` at 12500 cents; above 35.0 and up to and including 60.0 miles is `ZONE_3` at 18000 cents; anything above 60.0 miles is `OUT_OF_AREA` and carries a trip fee of 0 cents, because such a property cannot be served at all. A distance of exactly 15.0 is `ZONE_1`, 15.01 is `ZONE_2`, exactly 60.0 is `ZONE_3` and 60.01 is `OUT_OF_AREA`. The resulting `service_zone` is stored on the property at creation and re-derived on every read of it.

A **well profile** describes the water source. It names its `property_id`, its own `jurisdiction_code` — which is deliberately independent of both the property's jurisdiction and the account's billing jurisdiction — a `well_type` of `DRILLED`, `DRIVEN` or `DUG`, a `depth_feet` between 10.0 and 1200.0 inclusive, and optionally a `pressure_tank_drawdown_gallons` between 1.0 and 120.0 inclusive that defaults to **6.0** when omitted. Two numbers are derived from the drawdown the moment the profile is created. The **duty-cycle ratio** is `PEAK_DEMAND_GAL_PER_HOUR`, 30 gallons per hour, divided by the drawdown, where the drawdown used in the division is the larger of the stored drawdown and `MIN_DRAWDOWN_GALLONS` (1.0 gallon), and the quotient is rounded half up to two decimal places. A drawdown of 12.0 gallons gives 2.50; 10.0 gives 3.00; 6.0 gives 5.00; 5.0 gives 6.00; 4.0 gives 7.50. That ratio is then banded into `duty_cycle_class`: a ratio of at most 3.00 is `LOW`, a ratio above 3.00 and at most 6.00 is `MODERATE`, and anything above 6.00 is `HIGH`. Both band ceilings are inclusive, so the default drawdown of 6.0 produces a ratio of exactly 5.00 and a class of `MODERATE`, a drawdown of exactly 10.0 produces exactly 3.00 and `LOW`, and a drawdown of 4.99 produces 6.01 and `HIGH`.

A new well profile also starts with `potability_status` `UNKNOWN`, `treatment_media` `NONE`, and `measured_yield_gpm`, `hardness_gpg`, `last_inspection_completed_at` and `advisory_reason` all null. The remaining enumerations are `SAFE`, `ADVISORY` and `UNSAFE` for potability, and `SEDIMENT`, `CARBON` and `SOFTENER_RESIN` alongside `NONE` for media.

Replacing a pressure tank outside a work order is its own recorded event. A `PlatformAdmin` or a `Technician` supplies a `new_drawdown_gallons` figure, which carries the same range as the attribute it overwrites — between 1.0 and 120.0 inclusive, and `ERR_VALIDATION` at the payload gate outside that band; the server writes it onto `pressure_tank_drawdown_gallons`, re-derives the duty-cycle ratio and then the duty-cycle class in that order, and — because the class may have moved — recomputes `interval_days_as_operated` and then `next_due_at` on every `ACTIVE` maintenance plan on that well. `interval_days_as_designed` is untouched, and so is any overdue latch. The well's `version` and each touched plan's `version` each rise by 1. This is the seam where a purely mechanical repair reaches backwards and changes the due date of a plan created months earlier.

A well may be **shared** between properties. A `PlatformAdmin` or `BillingClerk` records a share by naming a `well_profile_id`, an `account_id` and a `split_pct` between 0.01 and 100.00 inclusive, expressed in percent with two decimals. Each agreement's `status` starts `ACTIVE` and the only other member is `TERMINATED`. Two rules guard creation, in this order. First, no `ACTIVE` agreement may already link that well to that account; a repeat is refused with `ERR_DUPLICATE_SHARED_WELL_AGREEMENT`. Second, after the write the `ACTIVE` shares on the well must not **exceed** 100.00 in total and must not number more than `SHARED_WELL_MAX_PARTIES` (4); a violation of either is refused with `ERR_SHARED_WELL_SPLIT_INVALID`. Under-allocation is deliberately *permitted* at creation time — the exact-100.00 identity is required only for the split to actually be applied when invoices are built, as Section 3.11 describes. Terminating an agreement sets its `status` to `TERMINATED` and raises its `version` by 1; because the 100.00 identity is enforced only on creation, a termination may legitimately leave a well under-allocated. Termination carries **no** state precondition and has no invalid-state error of its own: terminating an agreement that is already `TERMINATED` succeeds again, writes `TERMINATED` again and raises its `version` again.

Field labour is carried by **technicians**. A technician row holds a `full_name`, a `tier` of `APPRENTICE`, `JOURNEYMAN` or `MASTER`, a `status` of `AVAILABLE` or `OFF_DUTY` defaulting to `AVAILABLE`, and a `home_jurisdiction_code`. The `id` of a technician row is exactly the `X-User-ID` a `Technician` actor presents. Availability is mutable by a `PlatformAdmin` or a `Dispatcher` and bumps the row's `version` by 1.

The **parts catalog** holds one row per purchasable item: a `part_number`, which the business treats as unique across the catalog although the server enforces no such uniqueness — there is no error for a duplicate `part_number` and a second row carrying one is created normally — a `category` of `PUMP`, `PRESSURE_TANK`, `FILTRATION`, `CONTROL` or `CONSUMABLE`, a `unit_cost_cents` landed cost between 1 and 5000000 inclusive, and four category-specific attributes. `rated_gpm` is required for a `PUMP` and null otherwise; `rated_drawdown_gallons`, which must lie between 1.0 and 120.0 inclusive when present, is required for a `PRESSURE_TANK` and null otherwise; `grain_capacity` is required when the category is `FILTRATION` and the `media_kind` is `SOFTENER_RESIN`, and null otherwise; `media_kind` names the filtration media the part supplies and defaults to `NONE`, its other members being `SEDIMENT`, `CARBON` and `SOFTENER_RESIN`. "Required for a category and null otherwise" means both halves literally. Where the category calls for the attribute and it is absent, the creation is refused with `ERR_VALIDATION`. Where the category does **not** call for it, whatever the client supplied is **discarded**: the row stores null and every later read renders null, never the value sent — a `rated_gpm` posted on a `FILTRATION` part is not echoed back. Discarding happens after the payload gate has had its say, so a value that also breaks the field's own declared range — `rated_drawdown_gallons` outside 1.0 to 120.0, whatever the category — still fails there first. Stock is held in `on_hand_qty`, which defaults to 0. `status` defaults to `ACTIVE` and may be `DISCONTINUED`. A `PlatformAdmin` may later change `unit_cost_cents`, `on_hand_qty` or `status`, bumping `version` by 1 — and a cost change deliberately does **not** disturb a quote line whose cost has already been pinned.

### 3.2. Inspection and the Duty-Cycle Cascade

An inspection is booked by a `Dispatcher` or `PlatformAdmin` against a `well_profile_id` and a `technician_id`, with a planned `scheduled_for` instant. It opens in `SCHEDULED`; the other states are `IN_PROGRESS`, `COMPLETED` and `CANCELLED`, the last two terminal.

The assigned technician begins the visit, taking the inspection `SCHEDULED → IN_PROGRESS`. Two conditions guard it beyond the state itself: the acting `X-User-ID` must equal the inspection's `technician_id`, and the technician's own `status` must be `AVAILABLE` — an `OFF_DUTY` technician is refused with `ERR_TECHNICIAN_UNAVAILABLE`. The inspection's `version` rises by 1. Starting an inspection that is not in `SCHEDULED` is refused with `ERR_INSPECTION_INVALID_STATE`, and that same error guards completion and cancellation.

Completion is where the domain's most far-reaching cascade fires. The technician supplies all three measurements — `measured_yield_gpm`, which must lie between 0.0 and 200.0 inclusive, `static_level_feet`, and `observed_drawdown_gallons`, which must lie between 1.0 and 120.0 inclusive — and any of the three being absent is a payload failure. The inspection stores the three figures, stamps `completed_at` from the logical clock and moves `IN_PROGRESS → COMPLETED`. Then, in this exact order: the well's `measured_yield_gpm` is set from the inspection's, and the well's `last_inspection_completed_at` is set from the inspection's `completed_at`; the well's `pressure_tank_drawdown_gallons` is set from the inspection's `observed_drawdown_gallons`, so the duty-cycle ratio is recomputed; because the ratio moved, `duty_cycle_class` is re-banded; because the class moved, every `ACTIVE` maintenance plan on the well recomputes `interval_days_as_operated`; and because the interval moved, those plans recompute `next_due_at`. The plans' `compliance_state` is deliberately **not** re-derived here — an overdue latch survives this recomputation intact. The inspection's `version`, the well's `version` and each touched plan's `version` each rise by 1.

Cancellation is a dispatcher's act and is available from either `SCHEDULED` or `IN_PROGRESS`; it moves the inspection to `CANCELLED` and raises its `version` by 1. Nothing on the well is touched by a cancellation.

### 3.3. Water Quality: Panels, Hold Times, Confirmation and Potability

A water sample is recorded by a `Technician`, `ComplianceOfficer` or `PlatformAdmin` naming the `well_profile_id`, the `collected_by_technician_id`, a `panel_type` of `BACTERIOLOGICAL` or `CHEMICAL`, and the `sample_datetime` at which the sample was drawn. The row opens with `result_status` `COLLECTED` and `parent_test_id` null. The full result enumeration is `COLLECTED`, `ANALYZED_NEGATIVE`, `ANALYZED_PRESUMPTIVE_POSITIVE`, `ANALYZED_CHEMICAL_EXCEEDANCE`, `INVALID_HOLD_TIME`, `CONFIRMED_POSITIVE` and `CLEARED_NEGATIVE`; all but `COLLECTED` and `ANALYZED_PRESUMPTIVE_POSITIVE` are terminal.

**A sample analysed beyond its hold time is worthless regardless of what the analysis says.** When a `ComplianceOfficer` records the laboratory result it supplies `analyzed_at` and, optionally, the analytes: `coliform_present` for a bacteriological panel, and `nitrate_mg_l`, `arsenic_mg_l`, `lead_mg_l`, `iron_mg_l` and `hardness_gpg` for a chemical one. Elapsed hold time is the number of hours from `sample_datetime` to `analyzed_at`. The limit is `HOLD_TIME_HOURS_BACTERIOLOGICAL`, 30 hours, for a bacteriological panel and `HOLD_TIME_HOURS_CHEMICAL`, 336 hours, for a chemical one, and the test is **right-closed**: exactly 30.0 hours on a bacteriological sample is valid, 30 hours and one second is not. An `analyzed_at` that precedes `sample_datetime` is a payload failure — `ERR_INVALID_DATE_RANGE` — and never reaches the hold-time test.

Whichever branch the test takes, **every analyte the body supplied is written onto the test row itself**, and every analyte it omitted is written as null — so a bacteriological panel that carried a `hardness_gpg` stores that figure on the test even though only a chemical panel ever copies it onto the well, and a chemical panel that carried a `coliform_present` stores it and does nothing else with it.

When the hold time is exceeded, the test lands in `INVALID_HOLD_TIME` with `hold_time_valid` false, the analytes, `analyzed_at` and `recorded_by_user_id` stored, and — critically — **the well's `potability_status` does not move at all**. The result is discarded as evidence. This outcome does *not* raise `ERR_WATER_TEST_HOLD_TIME_EXCEEDED`; that error is reserved exclusively for a confirmatory sample that breaches its own hold time.

When the hold time is satisfied, the panel decides the branch, and `hold_time_valid` is set true with `analyzed_at` and `recorded_by_user_id` stored in every branch.

- A bacteriological panel reporting `coliform_present` false lands in `ANALYZED_NEGATIVE`, sets the well's `potability_status` to `SAFE` and clears `advisory_reason`. Only an explicit `true` is a presumptive finding, so a bacteriological result that **omits** `coliform_present` altogether takes this same branch and lands in `ANALYZED_NEGATIVE` with the stored `coliform_present` left null.
- A bacteriological panel reporting `coliform_present` true lands in `ANALYZED_PRESUMPTIVE_POSITIVE`, sets the well to `ADVISORY` and latches `advisory_reason` to `PRESUMPTIVE_COLIFORM`. This state is **not** terminal: a presumptive finding is an open question, not a result.
- A chemical panel always lands in `ANALYZED_CHEMICAL_EXCEEDANCE`, whatever its numbers say, and always copies its `hardness_gpg` onto the well's `hardness_gpg` — **including when the panel carried no `hardness_gpg` at all**, in which case the well's `hardness_gpg` is overwritten with null. The well moves to `ADVISORY` with `advisory_reason` `CHEMICAL_EXCEEDANCE` only when at least one declared maximum contaminant level is exceeded — nitrate above 10.0, arsenic above 0.010, lead above 0.015 or iron above 0.30 milligrams per litre, each comparison strict — and otherwise the well's potability is left exactly where it was. A chemical panel **latches at this instant**; there is no confirmatory step for chemistry.

In every branch that writes the well, both the test's `version` and the well's `version` rise by 1; in a branch that leaves the well untouched, only the test's `version` rises. On this capability the `INVALID_HOLD_TIME` branch is the **only** one that leaves the well untouched. In particular a chemical panel inside its hold time writes the well's `hardness_gpg` in every case, so its `version` rises even when no maximum contaminant level was exceeded and `potability_status` and `advisory_reason` did not move at all. Recording a laboratory result on a test that is not in `COLLECTED` is refused with `ERR_WATER_TEST_INVALID_STATE`.

A presumptive positive is resolved by a **confirmatory retest**, recorded by a *different* `ComplianceOfficer`. The body carries `confirm_sample_datetime`, `confirm_analyzed_at`, `confirm_coliform_present` and the `collected_by_technician_id` who drew the confirming sample. Three regulatory checks run before anything is written: the confirming sample must have been drawn within `RETEST_WINDOW_DAYS` (21 days) of the parent's `sample_datetime`, right-closed, or the call is refused with `ERR_RETEST_WINDOW_EXPIRED`; the confirming sample's own analysis must fall within the bacteriological hold time of 30 hours from `confirm_sample_datetime` to `confirm_analyzed_at`, right-closed, or the call is refused with `ERR_WATER_TEST_HOLD_TIME_EXCEEDED`; and the acting `X-User-ID` must differ from the parent's stored `recorded_by_user_id`, or the call is refused with `ERR_CONFIRMATORY_SAME_OFFICER`.

When the confirming sample reports coliform **absent**, the parent moves `ANALYZED_PRESUMPTIVE_POSITIVE → CLEARED_NEGATIVE`, a child `WaterTest` row is created carrying `parent_test_id` pointing at the parent, `well_profile_id` copied from the parent, `collected_by_technician_id` set to the technician named in the body, `panel_type` `BACTERIOLOGICAL`, `sample_datetime` and `analyzed_at` taken from the body's `confirm_sample_datetime` and `confirm_analyzed_at`, `coliform_present` taken from `confirm_coliform_present`, `hold_time_valid` true, `result_status` `CLEARED_NEGATIVE`, every chemical analyte null, and both `recorded_by_user_id` and `confirmed_by_user_id` null — the officer identifiers live on the parent, never on the child; `confirmed_by_user_id` is stored on the parent, the well returns to `SAFE` and `advisory_reason` is cleared, and both `version` counters rise by 1. When it reports coliform **present**, exactly the mirror writes happen with `CONFIRMED_POSITIVE` in place of `CLEARED_NEGATIVE` and the well moving to `UNSAFE` with `advisory_reason` `CONFIRMED_COLIFORM` — and then the call returns `ERR_RETEST_CONFIRMED_POSITIVE`, with every one of those writes persisting, as Section 2.11 sets out.

If nobody confirms at all, the fail-safe latch applies. A `ComplianceOfficer` or `PlatformAdmin` runs the retest-window lapse sweep against the presumptive test. The sweep requires that the elapsed time from the test's `sample_datetime` to the logical clock be **strictly greater** than 21 days; called while the window is still open it fails at the business gate with `ERR_RETEST_WINDOW_STILL_OPEN` and writes nothing. When the window has genuinely closed, the test latches to `CONFIRMED_POSITIVE` and the well moves to `UNSAFE` with `advisory_reason` `RETEST_WINDOW_LAPSED`; both `version` counters rise by 1.

Potability itself is a cycle, not a ladder. A well starts `UNKNOWN`. A clean bacteriological result takes it to `SAFE`; a presumptive positive or a chemical exceedance takes it from `UNKNOWN` or `SAFE` to `ADVISORY` and latches `advisory_reason`; a confirming retest or a lapsed window takes `ADVISORY` to `UNSAFE`; a clearing retest takes `ADVISORY` back to `SAFE` and clears `advisory_reason`. **`UNSAFE` is not terminal** — a later independent bacteriological panel with coliform absent, inside its own hold time, restores `SAFE` and clears `advisory_reason`. Every one of these movements is a side effect of a water-test transition; there is no endpoint that sets potability directly.

### 3.4. Treatment Recommendation and Softener Sizing

A `ComplianceOfficer` or `PlatformAdmin` founds a **treatment recommendation** on a well by naming the `water_test_id` of the chemical panel whose analytes justify it, together with `expected_well_profile_version` for the concurrency check of Section 2.8. The cited test must be a `CHEMICAL` panel that reached `ANALYZED_CHEMICAL_EXCEEDANCE`; a test of the other panel type, or one whose `result_status` is anything else, is refused with `ERR_NO_TREATMENT_INDICATED` — the very error the media walk below uses when no clause matches, and there is no separate answer for the wrong panel. That check runs after the cited `water_test_id` has been resolved at G9A, so an unresolvable identifier is `ERR_WATER_TEST_NOT_FOUND` first.

Media selection walks a **pinned clause order** and the first matching clause wins, which is what makes the answer well defined for a sample that trips several thresholds at once. If the test's `hardness_gpg` is present and is at least `HARDNESS_TREATMENT_TRIGGER_GPG` (7.0 grains per gallon — exactly 7.0 triggers), the `recommended_media` is `SOFTENER_RESIN`. Otherwise, if `iron_mg_l` is present and strictly above 0.30 milligrams per litre, the media is `SEDIMENT`. Otherwise, if `nitrate_mg_l` is present and strictly above 10.0, or `arsenic_mg_l` is present and strictly above 0.010, or `lead_mg_l` is present and strictly above 0.015, the media is `CARBON`. If no clause matches, no media can be selected and the creation is refused with `ERR_NO_TREATMENT_INDICATED`. Note the asymmetry: hardness triggers at or above its threshold, while every contaminant level triggers only strictly above — an analyte sitting exactly on its maximum contaminant level does not trigger.

When and only when the media is `SOFTENER_RESIN`, three further figures are sized in sequence. The **design grain load** is the test's `hardness_gpg` multiplied by the property's `household_size`, multiplied by `WATER_USE_GAL_PER_PERSON_PER_DAY` (75 gallons per person per day), multiplied by `REGEN_INTERVAL_DAYS` (7 days), rounded half up to a whole number and stored as `design_grains`. With a household of 5 that comes to hardness times 2625: hardness 20.0 gives 52500, hardness 30.0 gives 78750, hardness 31.0 gives 81375, and a household of 4 at hardness 8.0 gives 16800.

That grain load then selects a **capacity band**, and each band carries its own salt burn per regeneration. All upper bounds are inclusive and the final row has no upper bound at all:

| Design grains | `selected_capacity` | Salt pounds per regeneration |
| --- | --- | --- |
| at most 24000 | `CAP_24000` | 6 |
| above 24000, at most 32000 | `CAP_32000` | 9 |
| above 32000, at most 48000 | `CAP_48000` | 12 |
| above 48000, at most 64000 | `CAP_64000` | 15 |
| above 64000, at most 80000 | `CAP_80000` | 18 |
| above 80000 | `DUAL_TANK_64000` | 15 |

The last row is a genuine **step down**: a dual-tank unit alternates two 64000-grain resin beds, so each regeneration consumes less salt than the single-tank band beneath it even though total capacity is larger. Finally, `monthly_salt_lbs` is the selected band's salt per regeneration multiplied by 30 and divided by `REGEN_INTERVAL_DAYS` (7), rounded half up to one decimal place: 6 pounds per regeneration gives 25.7, 9 gives 38.6, 12 gives 51.4, 15 gives 64.3 and 18 gives 77.1. The chain from hardness through design grains and capacity to monthly salt is therefore **not monotone**: with a household of 5, hardness 20.0 yields 64.3 pounds a month, hardness 30.0 yields 77.1, and hardness 31.0 drops back to 64.3. When the media is not `SOFTENER_RESIN`, `design_grains`, `selected_capacity`, `salt_lbs_per_regen` and `monthly_salt_lbs` are all null.

Expiry is anchored on the **water test's** `sample_datetime`, never on the recommendation's own `created_at`: `expires_at` is the sample instant plus `RECOMMENDATION_VALIDITY_DAYS` (180 days). A recommendation authored on day 179 of the sample is already one day from expiry. The stored `status` starts `PROPOSED` and may become `ACCEPTED` or `SUPERSEDED`; `EXPIRED` is deliberately **not** a stored value. Instead `status_effective` is derived at read time and at the accept precondition: it is `EXPIRED` when the stored status is `PROPOSED` and the logical clock has reached or passed `expires_at`, and otherwise it simply equals the stored status. The window is half-open, so at exactly `expires_at` the recommendation is already expired. Because the clock never moves backwards, once `EXPIRED` is observed it can never revert.

Creating a recommendation on a well sets **every earlier** `PROPOSED` or `ACCEPTED` recommendation on that well to `SUPERSEDED` with `superseded_by_id` pointing at the new row. Each recommendation so superseded has its own `version` raised by 1, and the well's `version` rises by 1; the new row itself opens at `version` 1.

A `CustomerContact` accepts a recommendation on its own well. Three business conditions guard it beyond the stored status being `PROPOSED` — which, if violated, is `ERR_TREATMENT_RECOMMENDATION_INVALID_STATE`. Two of them share the business gate and are evaluated **in the order given here: expiry first, potability second.** The recommendation must not be effectively expired, or the answer is `ERR_TREATMENT_RECOMMENDATION_EXPIRED`; an expired recommendation on a well with an unresolved bacteriological question is therefore answered `ERR_TREATMENT_RECOMMENDATION_EXPIRED`, not `ERR_POTABILITY_PENDING_CONFIRMATION`. The well must not be sitting at `ADVISORY` with `advisory_reason` `PRESUMPTIVE_COLIFORM` — an unresolved bacteriological question blocks a treatment decision, and the refusal is `ERR_POTABILITY_PENDING_CONFIRMATION`. And the acting account must own the well through the property chain, or the refusal is the scope violation.

Acceptance installs the media and rewires the maintenance clocks. The well's `treatment_media` is set to `recommended_media`. Every `ACTIVE` maintenance plan on that well has its `filter_media` set to the same media and its `monthly_salt_lbs` set from the recommendation — which is 0.0 whenever the media is not `SOFTENER_RESIN` — and then recomputes `interval_days_as_operated` and `next_due_at`. The recommendation's `version`, the well's `version` and each touched plan's `version` each rise by 1.

### 3.5. The Costing Ladder: Labour and Parts

Both pipelines price labour and parts with the *same* derivation. It is set out once here and referred to from everywhere else.

**Labour.** The first step is to select a **time band** from a governing instant. The scheduled pipeline's estimate uses the quote's `estimated_start_at`; a work order's final figure uses its `actual_start_at`. The band is read from the instant in UTC. If its ISO weekday is Saturday or Sunday — weekday 6 or 7 — the band is `WEEKEND`, and weekend beats every hour band regardless of the hour. Otherwise, an hour of at least 8 and below 17 is `STANDARD`; an hour of at least 17 and below 22 is `EVENING`; every other hour, meaning 22 and 23 or anything from 0 up to but not including 8, is `NIGHT`. On the boundaries: `08:00:00.000Z` is `STANDARD`, `17:00:00.000Z` is `EVENING`, `22:00:00.000Z` is `NIGHT`.

The **hourly rate** is the tier's base rate multiplied by the band's multiplier, **rounded half up to whole cents here**, before anything else consumes it. The base rates are 6500 cents an hour for `APPRENTICE`, 9500 for `JOURNEYMAN` and 13500 for `MASTER`. The multipliers are 1.00 for `STANDARD`, 1.35 for `EVENING`, 1.75 for `NIGHT` and 1.50 for `WEEKEND`. A `JOURNEYMAN` in the evening is therefore 12825 cents an hour; a `MASTER` at the weekend is 20250; an `APPRENTICE` at night is 11375. On the estimate the tier is the quote's `quoted_technician_tier`; on the final figure it is the `tier` of the work order's assigned technician.

**Billable minutes** are the raw minutes rounded *up* to the next whole multiple of `BILLING_INCREMENT_MINUTES` (15), then floored at `MIN_BILLABLE_MINUTES` (60) — that is, the larger of the rounded figure and 60. Raw 0 becomes 60; raw 46 rounds to 60 and stays 60; raw 61 rounds to 75. One further step applies **only** on the emergency pipeline and **only** when the ticket's `cause_class` is `NON_WELL_CAUSE`: the result is then capped at `NON_WELL_CAUSE_LABOR_CAP_MINUTES` (60), so raw 200 minutes rounds to 210, floors at 210 and caps back down to 60. **This cap never applies to the quote estimate.** The raw minutes are the work order's `actual_labor_minutes` on the final figure and the quote's `estimated_labor_minutes` on the estimate.

The **labour charge** is the already-rounded hourly rate multiplied by billable minutes divided by sixty, rounded half up to whole cents a second time. A `JOURNEYMAN` in the evening with 100 raw minutes gives a rate of 12825, 105 billable minutes and a charge of 22444 cents. An `APPRENTICE` at night with 70 raw minutes gives 11375, 75 minutes and 14219 cents. A `MASTER` in the evening with 130 raw minutes gives 18225, 135 minutes and 41006 cents.

**Parts.** A part's **markup band** is chosen from its unit cost, and the markup is **flat on the whole unit cost, not marginal**. A unit cost of at most 5000 cents carries a markup of 0.60; above 5000 and at most 25000 carries 0.40; above 25000 and at most 100000 carries 0.28; above 100000 carries 0.18. All three band ceilings are inclusive. Because the bands are flat rather than marginal, the marked-up price is **not monotone** in cost: a unit cost of 5000 prices at 8000 while 5001 prices at 7001; 25000 prices at 35000 while 25001 prices at 32001; 100000 prices at 128000 while 100001 prices at 118001. A more expensive part can genuinely cost the customer less.

The **unit price** is the unit cost multiplied by one plus the markup fraction, rounded half up to whole cents *per unit*. The **extended price** is that rounded unit price multiplied by the quantity. A **parts subtotal** is the sum of the already-rounded extended prices over the status-filtered input set: for a quote, every line whose `status` is `ACTIVE`, ordered by `created_at` ascending; for an invoice, every consumption entry on the work order whose `status` is `POSTED`, ordered by `posted_at` ascending and then `created_at` ascending. Lines in `REMOVED`, `SUPERSEDED` or `SUPERSEDED_BY_YIELD` and entries in `REVERSED` are excluded from every subtotal.

### 3.6. The Scheduled Pipeline: Quotes, Lines, Pricing and Approval

An `Estimator` or `PlatformAdmin` opens a quote against an inspection. The cited inspection must resolve to a stored row, or the answer is `ERR_INSPECTION_NOT_FOUND`, but **its state is not examined at creation** — a quote may legitimately be opened against an inspection still in `SCHEDULED` or `IN_PROGRESS`, or one that was `CANCELLED`, and the requirement that it be `COMPLETED` and inside its validity window bites only at approval, below. Creation names the `property_id`, the `well_profile_id`, the `inspection_id` whose measured yield will gate pump lines, a `scope` of `NEW_WELL`, `PUMP_REPLACEMENT`, `PRESSURE_TANK`, `TREATMENT_INSTALL` or `REPAIR`, an `estimated_labor_minutes` between 15 and 720 inclusive, an `estimated_start_at` instant and a `quoted_technician_tier`. The quote opens in `DRAFT` with `parts_subtotal_cents`, `labor_subtotal_cents`, `permit_fee_cents`, `tax_cents` and `total_cents` all 0, and `sent_at`, `approved_at` and `approved_total_cents` all null. The full lifecycle is `DRAFT`, `PRICED`, `SENT`, `APPROVED`, `DECLINED`, `REVISION_REQUIRED`, `CONSUMED` and `EXPIRED`, with `DECLINED`, `CONSUMED` and `EXPIRED` terminal. A transition attempted from the wrong state is refused with `ERR_QUOTE_INVALID_STATE`.

An `Estimator` adds lines to a `DRAFT` or `REVISION_REQUIRED` quote, naming a `part_catalog_item_id`, a `quantity` and `expected_quote_version`. A line opens with `status` `ACTIVE`, `origin` `ESTIMATOR`, `superseded_by_line_id` null and its pricing fields — `unit_cost_cents_pinned`, `markup_pct_applied`, `unit_price_cents`, `extended_price_cents` — all null until the quote is priced. The other line statuses are `SUPERSEDED`, `SUPERSEDED_BY_YIELD` and `REMOVED`, and the other origin is `PERMIT_MANDATED_ALTERNATE`. Several business rules guard the add. The named part must exist, or the answer is `ERR_PART_CATALOG_ITEM_NOT_FOUND` at the business gate rather than at path existence. The part's `status` must be `ACTIVE`, or the answer is `ERR_PART_DISCONTINUED`. The `quantity` must not exceed `PART_MAX_LINE_QUANTITY` (50); note that the payload gate only checks that the quantity is a non-negative integer, so a quantity of 51 passes G8 and is refused at the business gate with `ERR_QUANTITY_EXCEEDS_LIMIT`, not with a validation error. A quantity of **0** is the other side of that coin: it passes G8, and no later rule refuses it either, so a zero-quantity line is created and later prices to an `extended_price_cents` of 0. A successful add raises the **quote's** `version` by 1 — the new line itself opens at `version` 1, as every freshly created row does — which is why each `expected_quote_version` in a run of successive adds differs from the one before it.

**Pump lines are gated on the well's measured yield.** When the named part's `category` is `PUMP`, three outcomes are possible. If the part's `rated_gpm` is strictly below `MIN_PUMP_GPM` (5.0), the line is refused with `ERR_YIELD_INSUFFICIENT_FOR_PUMP`. If the well has no `measured_yield_gpm` at all — no inspection has ever completed on it — the line is refused with `ERR_INSPECTION_REQUIRED`. Otherwise the pump is acceptable exactly when its `rated_gpm` is at most the well's `measured_yield_gpm` multiplied by `YIELD_SAFETY_FACTOR` (0.80), the comparison being **inclusive**; a pump above that ceiling would run the well dry and is refused, again with `ERR_YIELD_INSUFFICIENT_FOR_PUMP`. With a measured yield of 12.5 gallons a minute the ceiling is exactly 10.0, so a 10.0 pump passes and a 10.1 pump fails.

An `Estimator` may remove an `ACTIVE` line while the owning quote is `DRAFT` or `REVISION_REQUIRED`; the line moves to `REMOVED` and both the line's and the quote's `version` rise by 1. A removal attempted on a line that is not `ACTIVE`, or whose quote is in any other state, is refused with `ERR_QUOTE_LINE_INVALID_STATE`.

**Pricing** takes the quote `DRAFT → PRICED`, or `REVISION_REQUIRED → PRICED` on the revision cycle. At least one `ACTIVE` line must exist, or the call is refused with `ERR_QUOTE_HAS_NO_ACTIVE_LINES`. From `DRAFT`, every `ACTIVE` line has the catalog's *current* `unit_cost_cents` copied onto it as `unit_cost_cents_pinned` and frozen there — later catalog moves never disturb a pinned line — and then `markup_pct_applied`, `unit_price_cents` and `extended_price_cents` are computed per line by the parts ladder of Section 3.5. From `REVISION_REQUIRED` the behaviour differs in exactly one respect: lines whose pin is still null, which are the newly added permit-mandated alternates, are pinned from the current catalog cost, while lines that already carry a pin keep it frozen. In both cases all four money fields are then recomputed.

The quote total is assembled in a pinned order. `parts_subtotal_cents` is the sum of the extended prices of the `ACTIVE` lines. `labor_subtotal_cents` is the labour ladder run on the quote's own inputs — band from `estimated_start_at`, rate from `quoted_technician_tier`, minutes from `estimated_labor_minutes` with the emergency cap never applying. `permit_fee_cents` is the `fee_cents` of the permit raised from this quote whose `status` is `FILED`, `APPROVED` or `APPROVED_WITH_CONDITIONS`, taking the earliest such permit by `created_at`, and 0 when there is none. `tax_cents` is `TAX_RATE_PCT` (7.25 percent) applied to the **parts subtotal only** and rounded half up once — **labour is not taxable and neither is the permit fee**. `total_cents` is the sum of the four. Worked through: a single line on a part costing 25001 cents at quantity 2 gives a unit price of 32001 and a parts subtotal of 64002; an `estimated_start_at` of `2026-06-03T18:00:00Z`, a Wednesday evening, with a `JOURNEYMAN` tier gives a rate of 12825, and 100 estimated minutes give 105 billable minutes and a labour subtotal of 22444; with no permit the fee is 0; tax on 64002 is 4640; the total is 91086. Pricing raises the quote's `version` and each `ACTIVE` line's `version` by 1.

**Sending** takes `PRICED → SENT`, stamps `sent_at` from the logical clock and raises the quote's `version` by 1. That instant anchors the validity window.

**Approval** is the customer's act and it is the moment at which authorisation happens on this pipeline — *before* any work order exists. The acting account must own the quote through the property chain. Three business conditions are checked. The cited inspection must be `COMPLETED` and the elapsed time from its `completed_at` to the logical clock must be at most `INSPECTION_VALIDITY_DAYS` (365 days), right-closed, or the answer is `ERR_INSPECTION_STALE`. The owning account's `credit_hold` must be false, or the answer is `ERR_ACCOUNT_ON_CREDIT_HOLD`. And every `ACTIVE` line whose part category is `PUMP` must still clear the yield gate. On success the quote moves `SENT → APPROVED`, `approved_at` is stamped, `approved_total_cents` is latched from `total_cents`, and `version` rises by 1.

The validity window is deliberately **not** enforced at approval. It is enforced only by the explicit expiry sweep, which a `PlatformAdmin` runs against a `SENT` quote: the elapsed time from `sent_at` to the logical clock must be **strictly greater** than `QUOTE_VALIDITY_DAYS` (30 days), and the quote then moves `SENT → EXPIRED` with `version` up by 1. A sweep run while that window is still open — elapsed time not strictly greater than 30 days, which includes the sweep run at exactly 30 days — writes nothing and is refused with `ERR_QUOTE_INVALID_STATE`, the only 409 this capability has. Keeping the window out of the approval path is what keeps the staleness check above reachable after a long clock advance.

If a pump line has stopped clearing the yield gate — most obviously because a later inspection recorded a lower yield than the one the quote was priced against, but equally because the well now has no `measured_yield_gpm` at all or because the part's own `rated_gpm` sits below `MIN_PUMP_GPM` — approval takes the mutate-then-reject path of Section 2.11, and it takes it for **every** one of those failure modes alike: the approval never answers `ERR_INSPECTION_REQUIRED` the way the line-add capability does, only `ERR_QUOTE_LINE_YIELD_EXCEEDED`. Concretely: every offending `ACTIVE` pump line moves `ACTIVE → SUPERSEDED_BY_YIELD`, the quote moves `SENT → REVISION_REQUIRED`, the versions rise, and the call then returns `ERR_QUOTE_LINE_YIELD_EXCEEDED` with all of it persisted.

A customer may instead decline a `SENT` quote, moving it to `DECLINED` with `version` up by 1. And when a work order is finally raised against an `APPROVED` quote, the quote moves `APPROVED → CONSUMED` with `version` up by 1.

### 3.7. Permits and the Mandated-Alternate Cascade

Four scopes require a permit: `NEW_WELL`, `PUMP_REPLACEMENT`, `PRESSURE_TANK` and `TREATMENT_INSTALL`. `REPAIR` and `MAINTENANCE` do not.

A `ComplianceOfficer`, `Estimator` or `PlatformAdmin` opens a permit in `DRAFT` against a `well_profile_id`, with a `jurisdiction_code`, a `scope`, and optionally a `quote_id`, a `work_order_id`, an `expedited` flag defaulting to false and a `post_hoc` flag defaulting to false. `fee_cents` starts 0, `filed_at`, `jurisdiction_tier`, `mandated_alternate_part_id`, `superseded_quote_line_id` and `condition_text` all start null. The lifecycle is `DRAFT`, `FILED`, `APPROVED`, `APPROVED_WITH_CONDITIONS`, `REJECTED` and `WITHDRAWN`, with `APPROVED`, `APPROVED_WITH_CONDITIONS` and `WITHDRAWN` terminal; a transition from the wrong state is `ERR_PERMIT_INVALID_STATE`.

**Filing** is where the fee is computed and where the jurisdiction rule bites. The permit's `jurisdiction_code` must equal the **well's** `jurisdiction_code` — not the property's and emphatically not the account's `billing_jurisdiction_code` — or the filing is refused with `ERR_PERMIT_JURISDICTION_MISMATCH`. When `post_hoc` is true the linked work order must be `COMPLETED` and the elapsed time from its `actual_end_at` to the logical clock must be at most `POST_HOC_PERMIT_WINDOW_DAYS` (10 days), right-closed, or the filing is refused with `ERR_POST_HOC_PERMIT_WINDOW_EXPIRED`. A `post_hoc` permit that names **no** `work_order_id` at all fails this same check with this same error — there is no separate answer for the missing link. And no other permit for the same well and the same scope may already be `FILED`, `APPROVED` or `APPROVED_WITH_CONDITIONS`, or the filing is refused with `ERR_PERMIT_ALREADY_ON_FILE`.

The fee follows the **well's** jurisdiction tier. `JUR_ALPHA` is `TIER_A`, `JUR_BRAVO` is `TIER_B`, `JUR_CHARLIE` is `TIER_C` and `JUR_DELTA` is `TIER_B`. The base fees are 35000 cents for `TIER_A`, 22000 for `TIER_B` and 12000 for `TIER_C`. The scope multipliers are 3.0 for `NEW_WELL`, 1.0 for `PUMP_REPLACEMENT`, 0.5 for `PRESSURE_TANK`, 0.75 for `TREATMENT_INSTALL` and 0.0 for `REPAIR`. The base is multiplied by the scope multiplier and rounded half up to whole cents, and only then, when `expedited` is true, is the flat `EXPEDITE_FEE_CENTS` of 15000 added. A `JUR_ALPHA` new well not expedited is 105000; a `JUR_CHARLIE` treatment install, expedited, is 9000 plus 15000 for 24000; a `JUR_BRAVO` pressure tank not expedited is 11000. Filing stores `jurisdiction_tier` and `fee_cents`, stamps `filed_at` and raises `version` by 1.

A `FILED` permit may be **rejected**, which moves it to `REJECTED` with `version` up by 1, and a `REJECTED` permit may be returned to `DRAFT` by the refile capability, which clears `filed_at` back to null and resets `fee_cents` to 0 with `version` up by 1 — `jurisdiction_tier` is deliberately **left standing** at the value the earlier filing stored and is not cleared — closing the draft-file-reject-draft cycle. A `FILED` permit may also be **withdrawn**, moving it to `WITHDRAWN` with `version` up by 1.

**Approval** comes in two shapes, and which shape applies is decided by the pair `mandated_alternate_part_id` and `superseded_quote_line_id` alone. With **neither** present the permit simply moves `FILED → APPROVED` and its `version` rises by 1 — and a `condition_text` sent on its own, with neither of the pair, is **discarded**: the permit's `condition_text` stays null. Supplying exactly **one** of the pair is refused with `ERR_VALIDATION`. With **both** present — and optionally a `condition_text` — the jurisdiction is imposing an alternate part, and a four-hop cascade fires. The two identifiers are resolved at G9A in request-list order, so the part is resolved before the line: an unresolvable `mandated_alternate_part_id` answers `ERR_PART_CATALOG_ITEM_NOT_FOUND` even when the `superseded_quote_line_id` would not have resolved either. The remaining checks then run in exactly this order: the named quote line must belong to the permit's own `quote_id` and must still be `ACTIVE`, failing either of which is `ERR_QUOTE_LINE_INVALID_STATE`; then the named part must be `ACTIVE`, failing which is `ERR_PART_DISCONTINUED`; then the named part must share the superseded line's part `category`, failing which is `ERR_PART_CATEGORY_MISMATCH`. Then: the permit stores `condition_text`, `mandated_alternate_part_id` and `superseded_quote_line_id` and moves to `APPROVED_WITH_CONDITIONS`; the named line moves `ACTIVE → SUPERSEDED` with `superseded_by_line_id` pointing at a brand-new line created on the same quote with `origin` `PERMIT_MANDATED_ALTERNATE`, `status` `ACTIVE`, the same `quantity`, `part_catalog_item_id` set to the mandated part and `unit_cost_cents_pinned` left null — as are its `markup_pct_applied`, `unit_price_cents` and `extended_price_cents`, which all stay null until the quote is priced again, even though the quote total recomputed in the next hop already values that line; because the quote's `ACTIVE` line set changed, the quote moves `APPROVED → REVISION_REQUIRED` — or stays where it is if it was not `APPROVED` — and its subtotals, tax and `total_cents` are recomputed over the surviving `ACTIVE` lines, treating the un-pinned alternate at the catalog's *current* `unit_cost_cents`; and because the quote left `APPROVED`, every work order on that quote whose `fulfillment_status` is `SCHEDULED` moves to `HELD` with `hold_reason` `PERMIT_CONDITION_REVISION` and its scheduled window released. The permit's, the quote's, each touched line's and each touched work order's `version` each rise by 1.

### 3.8. The Emergency Pipeline: No Water at the Tap

An emergency ticket carries **two independent axes on the same row**. `dispatch_status` is the fulfilment axis and `authorization_status` is the money axis, and neither constrains the other except where a precondition names the other explicitly. A ticket can legitimately be on site with authorisation `NOT_REQUIRED`, diagnosed with authorisation `PENDING`, or diagnosed with authorisation `DECLINED`.

A `Dispatcher` or `PlatformAdmin` takes the call, naming the `property_id`, the `well_profile_id`, the `account_id` that placed the call and owns the authorisation decision, and `reported_outage_hours` between 0.0 and 240.0 inclusive. Intake stamps `intake_at` from the logical clock, copies the account's current `membership_tier` into `membership_tier_at_intake` — where it is frozen — and opens the ticket at `dispatch_status` `INTAKE` and `authorization_status` `NOT_REQUIRED`. `assigned_technician_id`, `dispatched_at`, `cause_class`, `severity_score`, `preauth_cap_cents`, `response_minutes` and `onsite_estimate_cents` all start null, and `dispatch_surcharge_cents`, `membership_credit_cents` and `net_dispatch_charge_cents` all start 0. The dispatch axis runs `INTAKE`, `TRIAGED`, `DISPATCHED`, `ON_SITE`, `DIAGNOSED`, `RESOLVED` and `CANCELLED`, the last two terminal; the authorisation axis runs `NOT_REQUIRED`, `PRE_AUTHORIZED`, `PENDING`, `AUTHORIZED` and `DECLINED`, with `DECLINED` terminal. A movement attempted from the wrong dispatch state is `ERR_EMERGENCY_DISPATCH_INVALID_STATE`; one attempted on the authorisation axis when it is not `PENDING` is `ERR_EMERGENCY_AUTH_INVALID_STATE`.

**Triage** takes `INTAKE → TRIAGED` and refuses a property whose `service_zone` is `OUT_OF_AREA` with `ERR_OUT_OF_SERVICE_AREA` — beyond 60.0 miles the company simply does not go. **Dispatch** takes `TRIAGED → DISPATCHED`: the dispatcher names a `technician_id`, which must resolve (or the answer is `ERR_TECHNICIAN_NOT_FOUND` at the business gate) and whose `status` must be `AVAILABLE` (or the answer is `ERR_TECHNICIAN_UNAVAILABLE`). The ticket stores `assigned_technician_id`, stamps `dispatched_at` and computes `response_minutes` as the whole minutes from `intake_at` to `dispatched_at`, taking the floor of the elapsed seconds divided by sixty. That figure is reported for operational metrics only and **never enters the price**. **Arrival** takes `DISPATCHED → ON_SITE` and may only be recorded by the assigned technician.

**Diagnosis** takes `ON_SITE → DIAGNOSED` and is the pivot of the whole pipeline. The assigned technician records a `cause_class` — `PUMP_FAILURE`, `WELL_DRY`, `PRESSURE_TANK_FAILURE`, `CONTROL_FAILURE`, `TREATMENT_FAILURE` or `NON_WELL_CAUSE` — and an `onsite_estimate_cents` between 0 and 10000000 inclusive. Five figures follow immediately.

The **severity score** is the sum of four components, capped at `SEVERITY_MAX` (100). Cause points are 45 for `WELL_DRY`, 40 for `PUMP_FAILURE`, 30 for `PRESSURE_TANK_FAILURE`, 25 for `CONTROL_FAILURE`, 20 for `TREATMENT_FAILURE` and 5 for `NON_WELL_CAUSE`. Outage points are the whole hours of `reported_outage_hours`, discarding any fractional hour, multiplied by 3, and then capped at 30. Household points are the property's `household_size` multiplied by 3, capped at 15. A vulnerable occupant adds a flat 10 points, and adds nothing when `has_vulnerable_occupant` is false. A control failure with 3.9 hours of outage, a household of 5 and a vulnerable occupant scores 25 plus 9 plus 15 plus 10, or 59. A pressure-tank failure with 5.0 hours, a household of 5 and no vulnerable occupant scores 60. A pump failure with 6.0 hours and a household of 4 scores 70. A dry well with 40.0 hours, a household of 12 and a vulnerable occupant scores 45 plus 30 plus 15 plus 10, capped to 100.

The **gross dispatch surcharge** is banded from that score with inclusive upper bounds: a score of at most 29 carries 7000 cents, a score from 30 through 59 carries 14000 cents, and a score of 60 or above carries 24000 cents.

The **membership credit** then applies against the surcharge. A `PREMIER` account earns a credit of the lesser of the surcharge and 20000 cents, **but only when the severity score is at least 60** — exactly 60 unlocks it — and 0 below that. A `SELECT` account earns the lesser of the surcharge and 5000 cents at every severity. A `NONE` account never earns a credit. The tier used is `membership_tier_at_intake`, the one latched at intake, not the tier read at diagnosis.

The **net dispatch charge** is the surcharge less the credit, floored at zero — except that a `NON_WELL_CAUSE` diagnosis zeroes it outright, because a tripped breaker or a municipal outage is not a well service and the billing basis collapses to the trip fee alone. Composed end to end, this chain is **not monotone in severity for a `PREMIER` account**: a score of 29 nets 7000, a score of 30 nets 14000, a score of 59 still nets 14000, and a score of 60 nets only 4000 because the credit unlocks. A more severe emergency can bill *less* than a moderate one. For a `SELECT` account the same chain is monotone non-decreasing — 2000, 9000, 9000, 19000, 19000 across scores 29, 30, 59, 60 and 100 — and for a `NONE` account it is 7000, 14000 and 24000.

The **pre-authorisation ceiling** is read from `membership_tier_at_intake` as well: 75000 cents for `NONE`, 100000 for `SELECT` and 150000 for `PREMIER`, stored as `preauth_cap_cents`. Finally, the **authorisation axis moves as a side effect of the diagnosis**: when `onsite_estimate_cents` is **strictly greater** than `preauth_cap_cents` the axis moves `NOT_REQUIRED → PENDING`, and otherwise it moves `NOT_REQUIRED → PRE_AUTHORIZED`. An estimate exactly equal to the cap is pre-authorised; one cent more is pending. The ticket's `version` rises by 1 for the whole diagnosis.

While the axis sits at `PENDING`, no parts may be consumed on the linked work order and the work order may not be completed. The customer resolves it either way. **Authorising** takes `PENDING → AUTHORIZED`; it may only be performed by the account named on the ticket, and the account's `credit_hold` must be false or the answer is `ERR_ACCOUNT_ON_CREDIT_HOLD`. **Declining** takes `PENDING → DECLINED`. A `DECLINED` ticket is the only way a diagnosed ticket closes without a work order: a dispatcher may then cancel it, taking `DIAGNOSED → CANCELLED`. Cancellation is otherwise available from `INTAKE` and from `TRIAGED` without further condition. Every one of these movements raises the ticket's `version` by 1.

The ticket reaches `RESOLVED` only as a side effect: when the work order founded on it completes, the dispatch axis moves `DIAGNOSED → RESOLVED`.

### 3.9. Work Orders: Scheduling, Execution, Parts and the Completion Cascade

A work order is the unit of actual field work, and like an emergency ticket it carries **two independent axes**. `fulfillment_status` runs `DRAFT`, `SCHEDULED`, `HELD`, `IN_PROGRESS`, `COMPLETED` and `CANCELLED`, the last two terminal. `billing_status` runs `NOT_BILLABLE`, `PENDING_INVOICE`, `INVOICED`, `SETTLED` and `WRITTEN_OFF`, the last two terminal. A completed work order can sit at `PENDING_INVOICE` indefinitely, and a cancelled one can still be written off. A movement from the wrong fulfilment state is `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`; from the wrong billing state it is `ERR_WORK_ORDER_INVALID_BILLING_STATE`.

A `Dispatcher` or `PlatformAdmin` creates one from **exactly one** origin. The body names `property_id`, `well_profile_id`, `assigned_technician_id`, a `scope` — the five quote scopes plus `MAINTENANCE` — and exactly one of `quote_id` or `emergency_ticket_id`. Supplying both, or neither, is refused with `ERR_WORK_ORDER_ORIGIN_CONFLICT`. A quote-founded work order requires that quote to be `APPROVED`, or the answer is `ERR_QUOTE_NOT_APPROVED`, and the quote then moves `APPROVED → CONSUMED` with its `version` up by 1. An emergency ticket may found **at most one** work order; a second attempt is refused with `ERR_EMERGENCY_TICKET_ALREADY_LINKED`, and the count that rule takes is of *every* work order already naming that ticket, cancelled ones included. The ticket's own dispatch axis is **not** examined here: a work order may legitimately be founded on a ticket still at `INTAKE`, `TRIAGED`, `DISPATCHED` or `ON_SITE`, or even on a `CANCELLED` one, and no error checks for `DIAGNOSED`. The three checks run in the order just given — origin conflict first, then the quote's approval, then the ticket's linkage — and all three run after the body's foreign keys have been resolved at G9A. The `pipeline` field is derived, not supplied: it is `EMERGENCY` when `emergency_ticket_id` is set and `SCHEDULED` in every other case — including a remedy work order raised from a callback claim, which carries neither a quote nor a ticket. The row opens at `fulfillment_status` `DRAFT` and `billing_status` `NOT_BILLABLE`, with `origin_callback_claim_id`, `hold_reason`, the scheduled and actual instants, `actual_labor_minutes`, `billable_minutes` and `labor_rate_cents_per_hour` all null, `labor_charge_cents` and `parts_charge_cents` 0, `callback_eligibility` `NONE` and `callback_attempt_count` 0. The other `callback_eligibility` members are `ELIGIBLE`, `CONSUMED` and `EXPIRED`.

**Scheduling** takes `DRAFT → SCHEDULED`, and it is where four gates land in a fixed order. First the regulatory ones. The permit prerequisite is satisfied when the scope needs no permit at all, **or** a permit whose `work_order_id` is this work order is `APPROVED` or `APPROVED_WITH_CONDITIONS`, **or** the pipeline is `EMERGENCY` — emergency work is permit-exempt and schedules and completes with no permit whatsoever. Failing all three is `ERR_PERMIT_REQUIRED_NOT_APPROVED`. Then the assigned technician's `tier` must satisfy the scope table below, failing which is `ERR_TECHNICIAN_TIER_INSUFFICIENT`:

| `scope` | Permitted technician tiers |
| --- | --- |
| `NEW_WELL` | `MASTER` only |
| `PUMP_REPLACEMENT` | `MASTER` only |
| `TREATMENT_INSTALL` | `JOURNEYMAN` or `MASTER` |
| `PRESSURE_TANK` | `APPRENTICE`, `JOURNEYMAN` or `MASTER` |
| `REPAIR` | `APPRENTICE`, `JOURNEYMAN` or `MASTER` |
| `MAINTENANCE` | `APPRENTICE`, `JOURNEYMAN` or `MASTER` |

Then two capacity rules, which use **deliberately different interval geometry**. The first is the technician overlap test. The candidate's `scheduled_start_at` is pushed back by `TRAVEL_BUFFER_MINUTES` (45) and its `scheduled_end_at` pushed forward by the same 45 minutes — the buffer expands the **candidate only** — and the buffered window is tested against every *other* work order of the same technician whose `fulfillment_status` is `SCHEDULED` or `IN_PROGRESS`, examined in order of `scheduled_start_at` ascending and then `created_at` ascending. Work orders in `DRAFT`, `HELD`, `COMPLETED` or `CANCELLED` are excluded. The windows collide when the buffered start is strictly before the other's end **and** the other's start is strictly before the buffered end; a collision is `ERR_TECHNICIAN_SCHEDULE_CONFLICT`. Because the buffer expands the candidate, two windows that merely touch **do** collide: against an existing window of 09:00 to 11:00 on a day, a candidate of 11:00 to 12:00 conflicts, while a candidate of 11:45 to 12:45 does not, because its buffered start lands exactly on 11:00 and the strict comparison fails.

The second is the per-well daily cap, which uses **day buckets, not intervals**. The candidate's `scheduled_start_at` is reduced to its UTC calendar date, and the count is of *other* work orders on the same well, in `SCHEDULED` or `IN_PROGRESS`, whose own `scheduled_start_at` falls on that same UTC date. If that count is at least `WELL_DAILY_WORK_ORDER_CAP` (1) the request is refused with `ERR_WELL_SERVICE_WINDOW_CONFLICT`. Only the start instant's date matters; a job running across midnight counts only against its start date. Scheduling stores `scheduled_start_at` and `scheduled_end_at`, clears `hold_reason` and raises `version` by 1. `scheduled_end_at` must be strictly after `scheduled_start_at`, failing which is `ERR_INVALID_DATE_RANGE` at the payload gate.

A scheduled work order can be pulled back to `HELD` when a permit condition revokes its quote's approval, as Section 3.7 describes; that clears its scheduled window and releases the technician's calendar. It returns from `HELD → SCHEDULED` through the same scheduling capability, which accepts a `HELD` work order exactly as it accepts a `DRAFT` one and re-runs all four of the scheduling conditions above afresh. The parent quote is **not** re-examined on that path: no error checks that the quote has returned to `APPROVED`, and the return is open whatever state the quote is in. `hold_reason` is cleared and the new window stored, closing the scheduled-held-scheduled cycle.

**Starting** takes `SCHEDULED → IN_PROGRESS`, may only be done by the assigned technician, and stamps `actual_start_at` from the logical clock. That instant — not the scheduled one — is what selects the labour time band at completion.

**Posting parts** is only possible against an `IN_PROGRESS` work order and only by its assigned technician. The body names a `part_catalog_item_id` and a `quantity`. The business gate then runs its checks **in this order**. First the part must exist, or the answer is `ERR_PART_CATALOG_ITEM_NOT_FOUND`. Then the two emergency-pipeline rules, which come ahead of everything about the part itself because they say no posting should be happening at all: a ticket diagnosed `NON_WELL_CAUSE` forbids parts entirely, refused with `ERR_NON_WELL_CAUSE_BLOCKS_PARTS`, and a ticket whose authorisation axis is `PENDING` refuses the posting with `ERR_AUTHORIZATION_REQUIRED`. Then the part must be `ACTIVE`, or the answer is `ERR_PART_DISCONTINUED`. Then the quantity must not exceed 50, or the answer is `ERR_QUANTITY_EXCEEDS_LIMIT` — a quantity of 0 passes here just as it passes the payload gate, and no later rule refuses it. Then the part's `on_hand_qty` must be at least the requested quantity, or the answer is `ERR_PART_OUT_OF_STOCK`. Last, on a `PRE_AUTHORIZED` emergency work order, the cumulative posted parts plus the work order's labour charge — the sum of the extended prices of every `POSTED` entry including the one being posted, plus the work order's current `labor_charge_cents`, which is 0 until completion — must not exceed the ticket's `preauth_cap_cents`, failing which is `ERR_PREAUTH_CAP_EXCEEDED`.

A posted entry stores `unit_cost_cents_snapshot`, `markup_pct_applied`, `unit_price_cents` and `extended_price_cents`, stamps `posted_at` from the logical clock and opens at `status` `POSTED`, the other member being `REVERSED`. The snapshot cost follows the invoice variant rule: on a work order founded on a quote, the snapshot is taken from the `unit_cost_cents_pinned` of the quote's `ACTIVE` line for the **same** `part_catalog_item_id`, choosing the earliest such line by `created_at`, and the catalog's current cost is used only for parts the quote never listed; on every other work order the snapshot is the catalog's *current* `unit_cost_cents` at posting time. Posting **immediately** decrements `on_hand_qty` by the quantity and raises the catalog part's `version` by 1.

**Completion** takes `IN_PROGRESS → COMPLETED` and is the largest cascade in the system. It may only be done by the assigned technician, requires `actual_labor_minutes` between 0 and 720 inclusive in the body, and is refused with `ERR_AUTHORIZATION_REQUIRED` when the pipeline is `EMERGENCY` and the ticket's authorisation axis is still `PENDING`. Eight hops then run in order:

1. `actual_end_at` is stamped from the logical clock, and `billable_minutes`, `labor_rate_cents_per_hour` and `labor_charge_cents` are computed by the labour ladder of Section 3.5 using `actual_start_at` for the band and the assigned technician's `tier` for the rate.
2. Every `POSTED` consumption entry on the work order is finalised: its `unit_cost_cents_snapshot`, `markup_pct_applied`, `unit_price_cents`, `extended_price_cents` and `posted_at` are frozen against any later catalog movement, and the work order's `parts_charge_cents` is set to the sum of their extended prices. No stock moves here — the decrement already happened at posting.
3. One `WarrantyCoverage` of `coverage_class` `PART` is minted per finalised entry, each naming its `parts_consumption_entry_id`, and **exactly one** of `coverage_class` `LABOR` is minted for the work order with `parts_consumption_entry_id` null. Every coverage takes `starts_at` from the work order's `actual_end_at` and computes `expires_at` as that instant plus `PART_WARRANTY_DAYS` (365 days) for a part coverage or `LABOR_WARRANTY_DAYS` (90 days) for the labour coverage — two different windows anchored on the same instant. Each opens with `status` `ACTIVE` and `claim_count` 0. When this work order carries an `origin_callback_claim_id`, the coverage named by that claim moves `ACTIVE → SUPERSEDED` with its `superseded_by_id` pointing at the newly minted coverage of the same class. Exactly one `LABOR` coverage is minted, so that class is unambiguous; when the completion finalised several entries and therefore minted several `PART` coverages, the one recorded is the **first** of them in mint order — the coverage of the earliest `POSTED` entry by `posted_at` ascending and then `created_at` ascending. Two edge cases are pinned. The supersede happens **only** when the named coverage's stored `status` is still `ACTIVE`; one already `SUPERSEDED` or already `VOIDED` is left entirely untouched. And when the class being superseded is `PART` while this completion finalised **no** consumption entries at all, there is no `PART` coverage to point at: the old coverage still moves to `SUPERSEDED`, and its `superseded_by_id` is left null.
4. The claim named by `origin_callback_claim_id` moves `APPROVED_WARRANTY → RESOLVED_REPAIRED`, and the **original** work order's `callback_eligibility` becomes `CONSUMED`. This hop is **not** conditional on hop 3 having found an `ACTIVE` coverage to supersede: it runs whenever the completing work order names a claim that stands in `APPROVED_WARRANTY`, and it does nothing at all when that claim stands in any other state.
5. Because parts and labour were finalised, first the well and only then every `ACTIVE` maintenance plan on it are refreshed, **in that order**: the well's `pressure_tank_drawdown_gallons` is set to the `rated_drawdown_gallons` of the finalised `PRESSURE_TANK` part when one is present — the earliest such part in the step-1 entry ordering when several were finalised — and `duty_cycle_ratio` and then `duty_cycle_class` are re-derived from it; only after the well has been re-banded is exactly one `MaintenanceVisit` row created per `ACTIVE` plan, with `visit_kind` chosen from the finalised part categories, and each plan's `interval_days_as_operated` re-derived from that freshly re-banded class. The well is refreshed even when the work order carries no `ACTIVE` plan at all, and no visit is created in that case.
6. Because the interval changed, `next_due_at` is recomputed from `last_service_date`; the salt and filter clocks are reset for whichever of them the visit touched; and `compliance_state` clears to `COMPLIANT` **only** when the visit kind is `SALT_AND_FILTER` or `FILTER_ONLY`.
7. Because the work order became billable, an `Invoice` is created in `DRAFT` with `variant` `QUOTED_PINNED` when `quote_id` is set and `ACTUAL_FINAL` otherwise, and its lines are constructed in the pinned order set out in Section 3.11.
8. Because an invoice exists, the work order's billing axis moves `NOT_BILLABLE → PENDING_INVOICE`; and when the pipeline is `EMERGENCY`, the ticket's dispatch axis moves `DIAGNOSED → RESOLVED`. The account's `balance_cents` is **not** touched at `DRAFT`.

The work order's `version`, each touched maintenance plan's `version`, the well's `version`, the emergency ticket's `version` when its dispatch axis moves to `RESOLVED`, and — on a remedy completion — the superseded coverage's, the resolved claim's and the **original** work order's `version` each rise by 1. Rows the cascade *creates* — the coverages, the visits, the invoice and its lines — open at `version` 1 like any other new row. Two points are pinned against the obvious alternative readings. **No catalog part is touched at completion**: hop 2 freezes prices and moves no stock, so a catalog part's `version` does not rise here — it rose already, at posting time. And the **well's `version` rises unconditionally** at every completion, whether or not a finalised `PRESSURE_TANK` part moved its drawdown and whether or not the re-derived duty-cycle figures actually changed.

**Cancellation** is a dispatcher's or admin's act and is available from `DRAFT`, `SCHEDULED` or `IN_PROGRESS`. From `SCHEDULED` it releases the technician's window, but it does so purely by leaving the `SCHEDULED`/`IN_PROGRESS` set that the overlap and daily-cap tests examine: `scheduled_start_at` and `scheduled_end_at` **stay stored on the cancelled row** as a historical record and are still rendered on every read of it. Only the `HELD` transition of Section 3.7 clears those two instants. From `IN_PROGRESS` it runs the inventory compensating action: every `POSTED` consumption entry on the work order moves to `REVERSED` and each catalog part's `on_hand_qty` is restored by exactly that entry's quantity, leaving the conservation identity of Section 2.12 exactly where it was before the postings. The work order's `version` and each touched part's `version` rise by 1.

**Write-off** is the `BillingClerk`'s act on the billing axis. It requires `billing_status` `NOT_BILLABLE` — checked first — and `fulfillment_status` `CANCELLED`, and moves the billing axis `NOT_BILLABLE → WRITTEN_OFF` with `version` up by 1. The billing axis also moves without any request of its own: `PENDING_INVOICE → INVOICED` when the linked invoice is issued, `INVOICED → SETTLED` when that invoice is paid in full, and `INVOICED → WRITTEN_OFF` when that invoice is voided.

### 3.10. Recurring Maintenance: Two Clocks and a Compliance Latch

A maintenance plan is opened by a `PlatformAdmin` or `Dispatcher` naming a `well_profile_id` and the `account_id` billed for maintenance. **At most one plan whose `status` is `ACTIVE` or `SUSPENDED` may exist per well**; a second is refused with `ERR_PLAN_ALREADY_EXISTS_FOR_WELL`. The plan's lifecycle axis runs `ACTIVE`, `SUSPENDED` and `TERMINATED`, the last terminal, and a movement from the wrong state — including a salt delivery, a filter change or a compliance evaluation on a plan that is not `ACTIVE` — is refused with `ERR_MAINTENANCE_PLAN_INVALID_STATE`. Its compliance axis runs `COMPLIANT` and `OVERDUE` and evolves independently.

The **maintenance interval** is the base interval for the well's `duty_cycle_class` less a reduction for the installed media, floored at `MIN_MAINTENANCE_INTERVAL_DAYS` (120 days). The base intervals are 365 days for `LOW`, 270 for `MODERATE` and 180 for `HIGH`. The media reductions are 0 days for `NONE`, 30 for `SEDIMENT`, 90 for `CARBON` and 0 for `SOFTENER_RESIN`. So a low-duty well with no media sits at 365 days, a moderate well with no media at 270, a high-duty well with no media at 180, a low-duty well on carbon at 275, a moderate well on carbon at 180, a high-duty well on sediment at 150, and a high-duty well on carbon at 120, where the floor binds.

That figure is computed **twice, with different lifetimes**. `interval_days_as_designed` is computed once at plan creation from the duty-cycle class and media in force at that instant, and then **frozen forever** — a later pressure-tank replacement leaves it untouched. `interval_days_as_operated` is recomputed on every duty-cycle change and every media change, and it alone drives `next_due_at`. The two disagree whenever the well has moved since the plan was created: a plan created while the well was `MODERATE` with no media freezes at 270, and a pressure-tank replacement that drops the drawdown to 4.0 gallons raises the ratio to 7.50, re-bands the class to `HIGH`, and leaves the operated interval at 180 — same plan, same well, 90 days apart.

At creation the plan sets both intervals, sets `last_service_date` to the plan's own `created_at`, sets `next_due_at` to `last_service_date` plus `interval_days_as_operated` days, mirrors `filter_media` from the well's `treatment_media`, and starts `monthly_salt_lbs` and `salt_remaining_lbs` at 0.0 with `last_filter_change_date`, `filter_next_due_date`, `last_salt_delivery_date`, `salt_next_due_date` and `overdue_latched_at` all null. `next_due_at` is always `last_service_date` plus `interval_days_as_operated` whole days, with the time-of-day component of the anchor preserved. `filter_next_due_date` and `salt_next_due_date` are, uniquely among the plan's fields, never stored: both are re-derived from the plan's current stored figures on **every read** of the plan, so a change to `filter_media`, `monthly_salt_lbs` or `salt_remaining_lbs` shows up in them immediately whether or not the writing capability names them.

**The two consumable clocks are driven by different physics and reset independently.** Salt is consumption-driven; filter media is time-driven. One visit can satisfy both, but each resets only its own clock.

The **salt clock** is anchored on the delivery date rather than on the logical clock, so the value is reproducible. It is null whenever `monthly_salt_lbs` is at most 0.0 or `last_salt_delivery_date` is still null. Otherwise the surplus is `salt_remaining_lbs` less `SALT_REORDER_THRESHOLD_LBS` (40 pounds); if that surplus is at most zero the day count is 0 and the salt is due on the delivery date itself; otherwise the day count is the surplus multiplied by 30 and divided by `monthly_salt_lbs`, taking the floor. `salt_next_due_date` is `last_salt_delivery_date` plus that many days. With 300.0 pounds remaining and a monthly burn of 64.3 the count is 121 days; with 100.0 remaining and 25.7 a month it is 70 days; with exactly 40.0 remaining and 64.3 a month it is 0.

A salt delivery is recorded by a `Dispatcher`, `Technician` or `PlatformAdmin` against an `ACTIVE` plan, supplying `delivered_lbs` and `expected_maintenance_plan_version`. A delivery smaller than `SALT_DELIVERY_MIN_LBS` (40.0 pounds) is refused at the payload gate with `ERR_VALIDATION`, and exactly 40.0 is allowed. A delivery that would push `salt_remaining_lbs` above `SALT_TANK_CAPACITY_LBS` (300 pounds) is refused with `ERR_SALT_DELIVERY_EXCEEDS_CAPACITY`, and landing exactly on 300.0 is allowed. On success the delivered pounds are added to `salt_remaining_lbs`, `last_salt_delivery_date` is stamped from the logical clock, `salt_next_due_date` is recomputed, and the plan's `version` rises by 1. A delivery **does not touch the filter clock and does not touch `compliance_state`**.

The **filter clock** is a fixed interval from the change date: 90 days for `SEDIMENT`, 180 days for `CARBON` and 1825 days for `SOFTENER_RESIN`. `filter_next_due_date` is null while `filter_media` is `NONE` and null while `last_filter_change_date` is null; otherwise it is `last_filter_change_date` plus the media's interval. A filter change is recorded by a `Technician`, `Dispatcher` or `PlatformAdmin` against an `ACTIVE` plan and takes no body. The plan's `filter_media` is **not** examined: a change recorded against a plan whose `filter_media` is `NONE` succeeds and stamps `last_filter_change_date` exactly as any other does, while `filter_next_due_date` stays null because that media carries no interval. Nor is a first change guarded by anything — the too-soon rule can only bite once a previous `last_filter_change_date` exists. A change recorded **fewer than** `FILTER_MIN_DAYS_BETWEEN_CHANGES` (30 days) after the previous one is refused with `ERR_FILTER_CHANGE_TOO_SOON`; exactly 30 days is allowed. On success `last_filter_change_date` is stamped from the logical clock, `filter_next_due_date` is recomputed and `version` rises by 1. A filter change **does not touch the salt clock and does not clear an overdue latch**.

Compliance is **latched, not derived**. A `PlatformAdmin` runs the evaluation against an `ACTIVE` plan; when that plan is `COMPLIANT` and the logical clock is **strictly past** `next_due_at`, the plan moves `COMPLIANT → OVERDUE`, `overdue_latched_at` is stamped from the logical clock and `version` rises by 1. The lifecycle axis is the only thing this capability refuses: a plan that is not `ACTIVE` is `ERR_MAINTENANCE_PLAN_INVALID_STATE`, while an `ACTIVE` plan the evaluation finds nothing to do for — one already latched at `OVERDUE`, or one whose `next_due_at` the clock has not yet passed — is answered 200 with the plan returned exactly as it stood and **no** `version` bump. That latch is never cleared by an interval recomputation that happens to push `next_due_at` back into the future — a naive as-of rule would silently un-overdue the plan, and the latch forbids it. The **only** thing that clears it is a qualifying maintenance visit, which moves `OVERDUE → COMPLIANT`, sets `overdue_latched_at` back to null and raises `version` by 1.

A visit is never created directly; exactly one is created per `ACTIVE` plan when a work order on the well completes. Its `visit_kind` is chosen from the finalised consumption entries of that work order: a filter is touched when any entry's part `category` is `FILTRATION`, and salt is touched when any entry's part `category` is `CONSUMABLE`. Both touched gives `SALT_AND_FILTER`; filter only gives `FILTER_ONLY`; salt only gives `SALT_ONLY`; neither gives `SERVICE_ONLY`. The visit records its `maintenance_plan_id`, its `work_order_id`, its `performed_at` from the logical clock, `filter_changed` true exactly when a filter was touched, and `salt_added_lbs` as the summed `quantity` of the `CONSUMABLE` entries multiplied by `SALT_LBS_PER_CONSUMABLE_UNIT` (40.0 pounds per unit), or 0.0 when none. When salt was touched, `salt_remaining_lbs` rises by `salt_added_lbs`, capped at 300 pounds, and `last_salt_delivery_date` is set to `performed_at`; when a filter was touched, `last_filter_change_date` is set to `performed_at`. **`compliance_state` clears only for `SALT_AND_FILTER` and `FILTER_ONLY`.**

`last_service_date`, by contrast, advances to the visit's `performed_at` on a visit of **any** kind, including `SALT_ONLY` and `SERVICE_ONLY` — which is exactly why a salt-only visit slides `next_due_at` forward while the plan stays `OVERDUE`. That behaviour is pinned; the naming tension it exposes is recorded, un-adjudicated, in Section 2.14.

A `PlatformAdmin` may suspend an `ACTIVE` plan, moving it to `SUSPENDED` with `version` up by 1, and may resume a `SUSPENDED` plan, which recomputes `interval_days_as_operated` and `next_due_at` from the current duty-cycle class and raises `version` by 1, closing the active-suspended-active cycle. A `SUSPENDED` plan may be terminated, moving it to `TERMINATED` with `version` up by 1; an `ACTIVE` plan cannot be terminated directly.

### 3.11. Invoicing, Shared-Well Splits and the Account Ledger

An invoice is never created by a request. It appears in `DRAFT` as the seventh hop of a work-order completion, with `variant` `QUOTED_PINNED` when the work order carries a `quote_id` and `ACTUAL_FINAL` otherwise. The two variants differ in exactly one respect — where a consumption entry's snapshot cost came from, as Section 3.9 sets out — and because the markup bands are flat, an invoice built on current catalog costs can land either above or below one built on pinned costs for the same parts and the same labour. The labour line always uses the **actual** billable minutes and the **actual** technician's tier, never the quoted ones, on both variants. The invoice lifecycle runs `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, `PAID_IN_FULL` and `VOID`, the last two terminal; a transition from the wrong state is `ERR_INVOICE_INVALID_STATE`.

**Construction runs in eleven pinned steps.**

1. The parts figure is the sum of the extended prices of the `POSTED` consumption entries of the work order, ordered by `posted_at` ascending and then `created_at` ascending. `REVERSED` entries are excluded.
2. The labour figure is the work order's `labor_charge_cents`.
3. The dispatch figure is 0 when the pipeline is `SCHEDULED`. On the emergency pipeline it is the ticket's `net_dispatch_charge_cents` plus the property's trip fee from its `service_zone` band.
4. The permit figure is the `fee_cents` of the permit whose `work_order_id` is this work order and whose `status` is `APPROVED` or `APPROVED_WITH_CONDITIONS`, taking the earliest such permit by `created_at`, and 0 when there is none.
5. The warranty credit is computed only when the completing work order carries an `origin_callback_claim_id`, and is otherwise zero in all three of its parts. When it applies, the claim named by that field points at an original work order; the part coverage is that original's coverage of class `PART` whose `status` is `ACTIVE` or `SUPERSEDED`, earliest by `created_at`, and the labour coverage is the same for class `LABOR`. **The two windows are checked separately against the same submission instant.** The whole days from the part coverage's `starts_at` to the claim's `submitted_at` must be at most 365 for the parts credit to apply, in which case the parts credit is the remedy work order's whole `parts_charge_cents`; the whole days from the labour coverage's `starts_at` to the same instant must be at most 90 for the labour credit to apply, in which case the labour credit is the remedy work order's whole `labor_charge_cents`. Both windows are right-closed on whole days. A claim raised on day 200 therefore credits parts in full and credits nothing for labour; a claim raised on day 90 credits both. `warranty_credit_cents` is the sum of the two, expressed as a positive number.
6. The pre-discount pre-tax figure is parts plus labour plus dispatch plus permit, less the warranty credit.
7. The loyalty discount is eligible when the account's `membership_tier` is one of `SELECT` or `PREMIER` **and** the pre-discount pre-tax figure from step 6 is at least `LOYALTY_DISCOUNT_MIN_PRETAX_CENTS` (200000 cents), the threshold being inclusive. The account whose tier is read here is the **property's own `account_id`** — the account the work order bills — read once at this step and never re-read per share, so the shared-well split of step 11 never changes which tier governed the discount, even when it writes invoices to other accounts entirely. When eligible, `loyalty_discount_cents` is `LOYALTY_DISCOUNT_PCT` (5.00 percent) of the **parts** figure, rounded half up, expressed as a positive number; otherwise it is 0. This is the pinned resolution of the circular-looking dependency between the discount and the total: the eligibility test reads the pre-discount figure and is never revisited.
8. `taxable_subtotal_cents` is the parts figure less the parts warranty credit less the loyalty discount, floored at 0.
9. `tax_cents` is `TAX_RATE_PCT` (7.25 percent) of `taxable_subtotal_cents`, rounded half up. **Nothing else is taxable** — not labour, not dispatch, not the trip fee, not the permit fee.
10. The undivided total is the pre-discount pre-tax figure, less the loyalty discount, plus the tax.
11. That undivided total is split across the well's shared-well agreements, as below.

Worked through on an emergency job for an account with no membership: one entry on a part costing 25001 cents at quantity 2 gives a unit price of 32001 and a parts figure of 64002; a `MASTER` starting in the evening with 130 raw minutes gives a rate of 18225, 135 billable minutes and 41006 of labour; a severity of 70 on a `NONE` tier gives a surcharge of 24000 with no credit, and a property at 20.0 miles is `ZONE_2` at 12500, so dispatch is 36500; the pre-discount pre-tax figure is 141508; the tier is not eligible so the discount is 0; the taxable base is 64002 and the tax is 4640; the undivided total is 146148. Change only the tier to `PREMIER` and the credit of 20000 unlocks at severity 70, netting dispatch to 4000 and dispatch overall to 16500; the pre-discount pre-tax figure falls to 121508, which is below 200000, so the loyalty discount does **not** apply even though the tier is eligible; the taxable base is still 64002 and the tax 4640, and the undivided total is 126148.

**The shared-well split.** The candidate shares are the `ACTIVE` agreements on the well, ordered by `created_at` ascending; `TERMINATED` agreements are excluded. If there are no such shares, or if their `split_pct` values do not total **exactly** 100.00, the split is not applied at all: one invoice is written to the property's own `account_id` for the whole undivided total, with `shared_split_pct` 100.00. Otherwise one invoice is written per share. Each share's raw amount is the undivided total multiplied by that share's `split_pct` divided by 100, taking the **floor**, and the whole remainder — the undivided total less the sum of the floored amounts — is added to the **first** share by `created_at` ascending, never by `id`. This guarantees the shares add back to the undivided total exactly. An undivided total of 9999 across two 50.00 shares gives 4999 and 4999 with a remainder of 1, so the first share takes 5000 and the second 4999. An undivided total of 10000 across shares of 33.33, 33.33 and 33.34 gives 3333, 3333 and 3334 with no remainder.

Each invoice records its `account_id`, its `work_order_id`, its `variant`, its `shared_split_pct` and its `total_cents` — the latter being that share's amount, or the whole undivided total in the single-invoice case. `parts_subtotal_cents`, `labor_subtotal_cents`, `dispatch_subtotal_cents`, `warranty_credit_cents`, `loyalty_discount_cents`, `taxable_subtotal_cents` and `tax_cents` carry the undivided work-order figures computed in steps 1 through 9. `amount_paid_cents` starts at 0 and `issued_at` is null while the invoice is `DRAFT`.

**Invoice lines** are constructed in this pinned order and numbered with `sequence_no` starting at 1 in that same order: every `PARTS` line first, one per `POSTED` consumption entry in the step-1 ordering, each naming its `parts_consumption_entry_id`; then the single `LABOR` line; then, on the emergency pipeline only, a `DISPATCH_SURCHARGE` line and a `TRIP_FEE` line; then a `PERMIT_FEE` line when a permit fee applies; then a `WARRANTY_CREDIT` line when the credit is greater than zero; then a `LOYALTY_DISCOUNT` line when the discount is greater than zero; then the `TAX` line. Each line carries an `invoice_id`, a human-readable `description` and a **signed** `amount_cents` — credits and discounts are **negative**, every other line type positive. The description is `Parts: <part_number> x <quantity>` on a `PARTS` line, naming the catalog part of the entry it was built from, and the fixed labels `Labour`, `Dispatch surcharge`, `Trip fee`, `Permit fee`, `Warranty credit`, `Loyalty discount` and `Tax` on the other seven line types. A `PERMIT_FEE` line appears only when the permit figure is non-zero, so a `REPAIR`-scope permit, whose scope multiplier is 0.0, produces no line at all; the `DISPATCH_SURCHARGE` and `TRIP_FEE` lines, by contrast, are written on every emergency invoice whether or not their amounts are zero. `parts_consumption_entry_id` is null on every line type other than `PARTS`. Invoice lines carry no `updated_at` and no `version`. When the shared-well split of step 11 writes several invoices, **each invoice in the set receives its own complete line set**, built in this same pinned order and numbered from `sequence_no` 1 again, and every line carries the **undivided** work-order amount: the split touches only each invoice's `total_cents` and `shared_split_pct`, never a line amount, so an invoice's lines do not sum to its own `total_cents` under a split.

**Issuing** is the `BillingClerk`'s act and it is the moment money moves. The linked work order must be `COMPLETED`, or the answer is `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`. The invoice moves `DRAFT → ISSUED`, `issued_at` is stamped from the logical clock, the account's `balance_cents` and `lifetime_invoiced_cents` each rise by the invoice's `total_cents`, `credit_hold` is re-derived, the work order's billing axis moves `PENDING_INVOICE → INVOICED`, and the invoice's, the account's and the work order's `version` each rise by 1. That last move happens only while the axis actually stands at `PENDING_INVOICE`: under a shared-well split the several invoices of one work order share that one work order, so the **first** issue carries the axis to `INVOICED` and raises the work order's `version`, and every later issue in the set finds the axis already there, leaves it alone and does not raise the work order's `version` again. Neither the account's `credit_hold` nor anything else about the account blocks an issue.

**Payments** are recorded by a `BillingClerk` against an `ISSUED` or `PARTIALLY_PAID` invoice, supplying `amount_cents` and `expected_invoice_version`. A zero amount passes the payload gate — it is not negative — and is refused at the business gate with `ERR_PAYMENT_AMOUNT_INVALID`. An amount greater than the outstanding balance, meaning `total_cents` less `amount_paid_cents`, is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`. An amount strictly between zero and the outstanding balance takes the invoice `ISSUED → PARTIALLY_PAID`, or leaves a `PARTIALLY_PAID` invoice in `PARTIALLY_PAID` — repeated part payments are legitimate, which is exactly why this endpoint carries concurrency control. An amount exactly equal to the outstanding balance takes the invoice to `PAID_IN_FULL` from either `ISSUED` or `PARTIALLY_PAID`, sets `amount_paid_cents` to `total_cents`, and moves the work order's billing axis `INVOICED → SETTLED` — again only while that axis actually stands at `INVOICED`, so under a shared-well split the first invoice of the set to settle carries the axis and a later one leaves it exactly where it stands. Every payment adds its amount to `amount_paid_cents` and to the account's `lifetime_paid_cents`, subtracts it from `balance_cents`, re-derives `credit_hold`, and raises the invoice's and the account's `version` by 1 — plus the work order's when the invoice settles.

**Voiding** is available from `ISSUED` and from `PARTIALLY_PAID` and runs the ledger's compensating action. The account's `balance_cents` falls by `total_cents` less `amount_paid_cents`, `lifetime_invoiced_cents` falls by `total_cents` and `lifetime_paid_cents` falls by `amount_paid_cents`, restoring the balance identity of Section 2.12 exactly. `amount_paid_cents` is deliberately **left on the invoice** as a historical record. `credit_hold` is re-derived, the work order's billing axis moves `INVOICED → WRITTEN_OFF` — once more only while that axis actually stands at `INVOICED`, so a void that finds it already `SETTLED` or already `WRITTEN_OFF` leaves it alone and does not raise the work order's `version` — and the invoice's, the account's and, when it moved, the work order's `version` each rise by 1.

### 3.12. Warranty, Callbacks and Remedy Work

Every completed work order leaves behind coverages, minted as described in Section 3.9: one of class `PART` per finalised consumption entry and exactly one of class `LABOR`. A coverage's stored `status` is `ACTIVE`, `SUPERSEDED` or `VOIDED`, the last two terminal, and its `coverage_state` is derived at read time: `EXPIRED` when the stored status is `ACTIVE` and the logical clock is **strictly past** `expires_at`, and otherwise simply the stored status. Coverage is right-closed — at exactly `expires_at` the coverage is still `ACTIVE`. A `PlatformAdmin` may void an `ACTIVE` coverage, provided no claim against it sits in `APPROVED_WARRANTY`. The `ACTIVE` this precondition reads is the **stored** `status`, never the derived `coverage_state`: a coverage the clock has carried past its `expires_at`, which therefore reads `EXPIRED`, is still stored `ACTIVE` and may still be voided. `ERR_WARRANTY_ALREADY_SUPERSEDED` is the one refusal this capability has, and it answers **both** grounds: a void attempted on a coverage whose stored status is already `SUPERSEDED` or already `VOIDED`, and a void blocked by a standing `APPROVED_WARRANTY` claim against a coverage that is otherwise `ACTIVE`. There is no distinct error for the second case.

**A callback claim is raised by the customer against the work order it complains about.** The body names the `warranty_coverage_id` being claimed against, a `complaint_class` of `PART` or `LABOR`, and a free-text `description`. That coverage is resolved at G9A — an unresolvable one is `ERR_WARRANTY_COVERAGE_NOT_FOUND` — and that resolution happens **before** the already-consumed test and before the warranty-window test below. The coverage is **not** required to have been minted by the addressed work order: nothing compares its `work_order_id` to the work order in the path, so a claim citing a coverage from an entirely different completion is accepted and is judged on that coverage's own `starts_at` and `expires_at`. The claim records its `original_work_order_id`, stamps `submitted_at` from the logical clock, opens at `status` `SUBMITTED` with `remedy_work_order_id` and `adjudicated_by_user_id` null, and exposes `days_since_coverage_start` as the whole days, floored, from the coverage's `starts_at` to `submitted_at`. **Every intake counts, in warranty or not**: the cited coverage's `claim_count` and the work order's `callback_attempt_count` each rise by 1 on the successful path exactly as they do on the rejected one, and both those rows' `version` rise by 1 with them. What the out-of-warranty path adds on top is the `REJECTED_OUT_OF_WARRANTY` status, the `callback_eligibility` of `EXPIRED` and the error; a successful intake leaves `callback_eligibility` exactly where it was. The claim lifecycle is `SUBMITTED`, `UNDER_REVIEW`, `APPROVED_WARRANTY`, `REJECTED_OUT_OF_WARRANTY`, `REJECTED_NOT_DEFECT` and `RESOLVED_REPAIRED`, the last three terminal; a movement from the wrong state is `ERR_CALLBACK_CLAIM_INVALID_STATE`. A claim against a work order whose `callback_eligibility` is already `CONSUMED` is refused with `ERR_CALLBACK_ALREADY_CONSUMED`.

**The `complaint_class` selects which window applies**, and that is what makes a single completion date in warranty on one axis and out of warranty on the other. The claim is in warranty when the coverage's `coverage_state` is `ACTIVE` and the whole days from `starts_at` to `submitted_at` are at most 365 for a `PART` complaint or at most 90 for a `LABOR` complaint. A labour claim filed exactly 90 days after the coverage started is in warranty; 91 days is not. A claim raised on day 200 against the same completion is out of warranty as `LABOR` and in warranty as `PART`. When the claim is **out** of warranty, the intake takes the mutate-then-reject path of Section 2.11 — the claim row is created durably in `REJECTED_OUT_OF_WARRANTY`, `claim_count` and `callback_attempt_count` rise, `callback_eligibility` is set to `EXPIRED`, and only then is `ERR_CALLBACK_OUT_OF_WARRANTY` returned, with the created claim readable afterwards through the ordinary reads.

**Adjudication** is performed by a `Technician` who is **not** the one assigned to the original work order; a self-adjudication is refused with `ERR_CALLBACK_ADJUDICATOR_CONFLICT`. The body carries a `decision` of `REVIEW`, `APPROVE` or `REJECT`. A `REVIEW` decision takes the claim `SUBMITTED → UNDER_REVIEW` and stores `adjudicated_by_user_id`. From `UNDER_REVIEW`, an `APPROVE` decision requires **only** that the coverage has not already been claimed `CALLBACK_MAX_PER_COVERAGE` (2) times: a `claim_count` **strictly beyond** that limit is refused with `ERR_CALLBACK_LIMIT_REACHED`, so a stored `claim_count` of 3 or more refuses while 2 still approves — and because intake increments `claim_count` before any adjudication, the limit first bites on the *third* claim raised against the same coverage. The coverage's own `coverage_state` is **not** re-examined at approval; no error is named for it and none is raised, so a coverage that has since expired or been superseded does not by itself block the approval. On success the decision takes the claim to `APPROVED_WARRANTY` and sets the **original** work order's `callback_eligibility` to `ELIGIBLE`, raising both `version` counters by 1. A `REJECT` decision from `UNDER_REVIEW` takes the claim to `REJECTED_NOT_DEFECT` and raises its `version` by 1, leaving the original work order's eligibility untouched. `adjudicated_by_user_id` is stored on **every** successful decision — approve and reject exactly as much as review — and always carries the adjudicating `X-User-ID`, overwriting whatever an earlier decision on the same claim had left there.

A `Dispatcher` raises the **remedy work order** from a claim in `APPROVED_WARRANTY` that does not already have one; any other claim state, or a claim that already carries a `remedy_work_order_id`, is refused with `ERR_CALLBACK_CLAIM_INVALID_STATE`. The body names the `assigned_technician_id` and the `scope`. A `DRAFT` work order is created with `origin_callback_claim_id` set to the claim, `pipeline` `SCHEDULED`, `property_id` and `well_profile_id` copied from the original work order, and both `quote_id` and `emergency_ticket_id` left null. The claim's `remedy_work_order_id` is set and its `version` rises by 1. When that remedy work order eventually completes, the coverage it remedies moves `ACTIVE → SUPERSEDED` with `superseded_by_id` pointing at the newly minted coverage of the same class, chosen exactly as Section 3.9 sets out, the claim moves `APPROVED_WARRANTY → RESOLVED_REPAIRED`, and the original work order's `callback_eligibility` becomes `CONSUMED` — and the remedy work order's own invoice carries the warranty credit computed in Section 3.11.

---

## 4. Endpoint Definitions

Creating a new resource answers **201 Created**; every other successful call, including every read, every state transition and every partial update, answers **200 OK**. Success bodies carry the created or updated resource in `data` unless the entry below says otherwise.

Two errors are omitted from the per-endpoint lists because they apply to **every** endpoint without exception: `ERR_UNAUTHENTICATED` when the identity headers are missing or the role is unrecognised, and `ERR_UNAUTHORIZED` when the named role is not in the endpoint's role list. Likewise, every endpoint accepting `limit` and `offset` can return `ERR_INVALID_PAGINATION`, and that is listed only once per entry. Where a request field is marked optional, its stated default applies when the field is omitted.

### 4.1. Logical Clock

**`POST /water-service/_clock/set_current_utc`** — advances the server's logical clock.
- Roles: `PlatformAdmin`. Success: 200, an object carrying `current_utc` and `previous_utc`.
- Request: `to_iso8601`.
- Errors: `ERR_VALIDATION`, `ERR_INVALID_TIMESTAMP`, `ERR_CLOCK_BACKWARD`.

**`GET /water-service/_clock`** — reads the current logical clock.
- Roles: all seven. Success: 200, an object carrying `current_utc`.
- Request: no body, no parameters.
- Errors: none beyond the universal two.

### 4.2. Accounts

**`POST /water-service/accounts`** — creates a billing account.
- Roles: `PlatformAdmin`. Success: 201, the created `Account`.
- Request: `legal_name`, `billing_jurisdiction_code`, `contact_email`, optional `membership_tier` (default `NONE`).
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

**`GET /water-service/accounts/{account_id}`** — reads one account.
- Roles: `PlatformAdmin`, `BillingClerk`, `Estimator`, `Dispatcher`, `CustomerContact`. Success: 200, the `Account`.
- Request: no body. Ownership is enforced for `CustomerContact`.
- Errors: `ERR_ACCOUNT_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`.

**`GET /water-service/accounts`** — lists accounts, `created_at` ascending.
- Roles: `PlatformAdmin`, `BillingClerk`. Success: 200, an array of `Account`.
- Request: optional filters `membership_tier`, `credit_hold`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`PATCH /water-service/accounts/{account_id}`** — changes an account's membership tier.
- Roles: `PlatformAdmin`. Success: 200, the updated `Account`.
- Request: `membership_tier`. Raises the account's `version` by 1 and never rewrites a ticket's `membership_tier_at_intake`.
- Errors: `ERR_ACCOUNT_NOT_FOUND`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

**`GET /water-service/accounts/{account_id}/invoices`** — every invoice of this account.
- Roles: `PlatformAdmin`, `BillingClerk`, `CustomerContact`. Success: 200, an array of `Invoice`.
- Request: optional `limit` and `offset`. Ownership is enforced for `CustomerContact`.
- Errors: `ERR_ACCOUNT_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_INVALID_PAGINATION`.

### 4.3. Properties

**`POST /water-service/properties`** — creates a serviced property under an account.
- Roles: `PlatformAdmin`, `Dispatcher`. Success: 201, the created `Property` with `service_zone` derived from `distance_miles`.
- Request: `account_id`, `address_line`, `jurisdiction_code`, `distance_miles`, `household_size`, optional `has_vulnerable_occupant` (default `false`).
- Errors: `ERR_VALIDATION`, `ERR_ACCOUNT_NOT_FOUND`.

**`GET /water-service/properties/{property_id}`** — reads one property.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`, `BillingClerk`, `CustomerContact`. Success: 200, the `Property`.
- Request: no body. No ownership check.
- Errors: `ERR_PROPERTY_NOT_FOUND`.

**`GET /water-service/properties`** — lists properties.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `BillingClerk`. Success: 200, an array of `Property`.
- Request: optional filters `account_id`, `jurisdiction_code`, `service_zone`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`GET /water-service/properties/{property_id}/well-profiles`** — every well profile on this property.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`, `ComplianceOfficer`. Success: 200, an array of `WellProfile`.
- Request: optional `limit` and `offset`.
- Errors: `ERR_PROPERTY_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

### 4.4. Well Profiles

**`POST /water-service/well-profiles`** — creates a well profile.
- Roles: `PlatformAdmin`, `Dispatcher`. Success: 201, the created `WellProfile` with `duty_cycle_ratio` and `duty_cycle_class` already derived and `potability_status` `UNKNOWN`.
- Request: `property_id`, `jurisdiction_code`, `well_type`, `depth_feet`, optional `pressure_tank_drawdown_gallons` (default `6.0`).
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_PROPERTY_NOT_FOUND`.

**`GET /water-service/well-profiles/{well_profile_id}`** — reads one well profile.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`, `ComplianceOfficer`, `CustomerContact`. Success: 200, the `WellProfile`.
- Request: no body. No ownership check.
- Errors: `ERR_WELL_PROFILE_NOT_FOUND`.

**`GET /water-service/well-profiles`** — lists well profiles.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`, `ComplianceOfficer`. Success: 200, an array of `WellProfile`.
- Request: optional filters `property_id`, `potability_status`, `duty_cycle_class`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/well-profiles/{well_profile_id}/pressure-tank-replacement`** — records a tank replacement outside a work order and re-derives every dependent maintenance interval.
- Roles: `PlatformAdmin`, `Technician`. Success: 200, the updated `WellProfile`.
- Request: `new_drawdown_gallons`.
- Errors: `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_VALIDATION`.

**`GET /water-service/well-profiles/{well_profile_id}/maintenance-plans`** — maintenance plans on this well.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `CustomerContact`. Success: 200, an array of `MaintenancePlan`.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

**`POST /water-service/well-profiles/{well_profile_id}/treatment-recommendations`** — founds a treatment recommendation on a chemical panel; carries concurrency control on the well.
- Roles: `ComplianceOfficer`, `PlatformAdmin`. Success: 201, the created `TreatmentRecommendation`.
- Request: `water_test_id`, `expected_well_profile_version`.
- Errors: `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_STALE_WELL_PROFILE_VERSION`, `ERR_VALIDATION`, `ERR_WATER_TEST_NOT_FOUND`, `ERR_NO_TREATMENT_INDICATED`.

### 4.5. Shared-Well Agreements

**`POST /water-service/shared-well-agreements`** — adds an account to a shared well with a percentage share.
- Roles: `PlatformAdmin`, `BillingClerk`. Success: 201, the created `SharedWellAgreement` in `ACTIVE`.
- Request: `well_profile_id`, `account_id`, `split_pct`.
- Errors: `ERR_VALIDATION`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_DUPLICATE_SHARED_WELL_AGREEMENT`, `ERR_SHARED_WELL_SPLIT_INVALID`.

**`GET /water-service/shared-well-agreements/{shared_well_agreement_id}`** — reads one agreement.
- Roles: `PlatformAdmin`, `BillingClerk`, `CustomerContact`. Success: 200, the `SharedWellAgreement`. No ownership check.
- Request: no body.
- Errors: `ERR_SHARED_WELL_AGREEMENT_NOT_FOUND`.

**`GET /water-service/shared-well-agreements`** — lists agreements.
- Roles: `PlatformAdmin`, `BillingClerk`. Success: 200, an array of `SharedWellAgreement`.
- Request: optional filters `well_profile_id`, `account_id`, `status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/shared-well-agreements/{shared_well_agreement_id}/terminate`** — terminates an agreement.
- Roles: `PlatformAdmin`. Success: 200, the updated `SharedWellAgreement` in `TERMINATED` with `version` up by 1.
- Request: no body. May legitimately leave the well under-allocated.
- Errors: `ERR_SHARED_WELL_AGREEMENT_NOT_FOUND`.

### 4.6. Technicians

**`POST /water-service/technicians`** — creates a technician; the returned `id` is the `X-User-ID` that technician presents.
- Roles: `PlatformAdmin`. Success: 201, the created `Technician`.
- Request: `full_name`, `tier`, `home_jurisdiction_code`, optional `status` (default `AVAILABLE`).
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

**`GET /water-service/technicians/{technician_id}`** — reads one technician.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `ComplianceOfficer`. Success: 200, the `Technician`. No ownership check.
- Request: no body.
- Errors: `ERR_TECHNICIAN_NOT_FOUND`.

**`GET /water-service/technicians`** — lists technicians.
- Roles: `PlatformAdmin`, `Dispatcher`. Success: 200, an array of `Technician`.
- Request: optional filters `tier`, `status`, `home_jurisdiction_code`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`PATCH /water-service/technicians/{technician_id}`** — changes a technician's availability.
- Roles: `PlatformAdmin`, `Dispatcher`. Success: 200, the updated `Technician` with `version` up by 1.
- Request: `status`.
- Errors: `ERR_TECHNICIAN_NOT_FOUND`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

### 4.7. Part Catalog

**`POST /water-service/part-catalog-items`** — creates a catalog part.
- Roles: `PlatformAdmin`. Success: 201, the created `PartCatalogItem`.
- Request: `part_number`, `category`, `unit_cost_cents`, optional `rated_gpm`, `rated_drawdown_gallons`, `grain_capacity` (each defaulting to null), optional `media_kind` (default `NONE`), optional `on_hand_qty` (default `0`), optional `status` (default `ACTIVE`).
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

**`GET /water-service/part-catalog-items/{part_catalog_item_id}`** — reads one catalog part.
- Roles: `PlatformAdmin`, `Estimator`, `Technician`, `Dispatcher`, `ComplianceOfficer`. Success: 200, the `PartCatalogItem`.
- Request: no body.
- Errors: `ERR_PART_CATALOG_ITEM_NOT_FOUND`.

**`GET /water-service/part-catalog-items`** — lists catalog parts.
- Roles: `PlatformAdmin`, `Estimator`, `Technician`, `Dispatcher`. Success: 200, an array of `PartCatalogItem`.
- Request: optional filters `category`, `media_kind`, `status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`PATCH /water-service/part-catalog-items/{part_catalog_item_id}`** — changes a part's cost, stock or availability; a cost change never disturbs a pinned quote line.
- Roles: `PlatformAdmin`. Success: 200, the updated `PartCatalogItem` with `version` up by 1.
- Request: optional `unit_cost_cents`, `on_hand_qty`, `status` — any subset, each leaving the field unchanged when omitted or supplied as explicit `null`. A request that supplies none of the three is still a successful 200 that leaves every field as it was and still raises `version` by 1.
- Errors: `ERR_PART_CATALOG_ITEM_NOT_FOUND`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

### 4.8. Inspections

**`POST /water-service/inspections`** — schedules a well inspection.
- Roles: `Dispatcher`, `PlatformAdmin`. Success: 201, the created `Inspection` in `SCHEDULED`.
- Request: `well_profile_id`, `technician_id`, `scheduled_for`.
- Errors: `ERR_VALIDATION`, `ERR_INVALID_TIMESTAMP`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`.

**`GET /water-service/inspections/{inspection_id}`** — reads one inspection.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`. Success: 200, the `Inspection`.
- Request: no body.
- Errors: `ERR_INSPECTION_NOT_FOUND`.

**`GET /water-service/inspections`** — lists inspections.
- Roles: `PlatformAdmin`, `Dispatcher`, `Estimator`, `Technician`. Success: 200, an array of `Inspection`.
- Request: optional filters `well_profile_id`, `technician_id`, `status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/inspections/{inspection_id}/start`** — the assigned technician begins the inspection.
- Roles: `Technician`. Success: 200, the updated `Inspection` in `IN_PROGRESS`.
- Request: no body.
- Errors: `ERR_INSPECTION_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_INSPECTION_INVALID_STATE`, `ERR_TECHNICIAN_UNAVAILABLE`.

**`POST /water-service/inspections/{inspection_id}/complete`** — records the three measurements and fires the duty-cycle cascade.
- Roles: `Technician`. Success: 200, the updated `Inspection` in `COMPLETED` with `completed_at` stamped.
- Request: `measured_yield_gpm`, `static_level_feet`, `observed_drawdown_gallons` — all three required.
- Errors: `ERR_INSPECTION_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_INSPECTION_INVALID_STATE`, `ERR_VALIDATION`.

**`POST /water-service/inspections/{inspection_id}/cancel`** — cancels a `SCHEDULED` or `IN_PROGRESS` inspection.
- Roles: `Dispatcher`, `PlatformAdmin`. Success: 200, the updated `Inspection` in `CANCELLED`.
- Request: no body.
- Errors: `ERR_INSPECTION_NOT_FOUND`, `ERR_INSPECTION_INVALID_STATE`.

### 4.9. Water Tests

**`POST /water-service/water-tests`** — records a collected water sample.
- Roles: `Technician`, `ComplianceOfficer`, `PlatformAdmin`. Success: 201, the created `WaterTest` in `COLLECTED` with `parent_test_id` null.
- Request: `well_profile_id`, `collected_by_technician_id`, `panel_type`, `sample_datetime`.
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_INVALID_TIMESTAMP`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`.

**`GET /water-service/water-tests/{water_test_id}`** — reads one water test.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Technician`, `Estimator`, `CustomerContact`. Success: 200, the `WaterTest`. No ownership check.
- Request: no body.
- Errors: `ERR_WATER_TEST_NOT_FOUND`.

**`GET /water-service/water-tests`** — lists water tests, including confirmatory children by their parent.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Technician`, `Estimator`. Success: 200, an array of `WaterTest`.
- Request: optional filters `well_profile_id`, `collected_by_technician_id`, `parent_test_id`, `panel_type`, `result_status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/water-tests/{water_test_id}/lab-result`** — records the laboratory analysis and routes the test to one of four outcomes.
- Roles: `ComplianceOfficer`. Success: 200, the updated `WaterTest`.
- Request: `analyzed_at`; optional `coliform_present`, `nitrate_mg_l`, `arsenic_mg_l`, `lead_mg_l`, `iron_mg_l`, `hardness_gpg`, each defaulting to null when omitted.
- Errors: `ERR_WATER_TEST_NOT_FOUND`, `ERR_WATER_TEST_INVALID_STATE`, `ERR_VALIDATION`, `ERR_INVALID_TIMESTAMP`, `ERR_INVALID_DATE_RANGE`.

**`POST /water-service/water-tests/{water_test_id}/confirmatory-result`** — records the confirmatory retest of a presumptive positive. A confirming outcome writes durably and *then* errors.
- Roles: `ComplianceOfficer`. Success: 200, the updated `WaterTest` in `CLEARED_NEGATIVE`.
- Request: `confirm_sample_datetime`, `confirm_analyzed_at`, `confirm_coliform_present`, `collected_by_technician_id`.
- Errors: `ERR_WATER_TEST_NOT_FOUND`, `ERR_WATER_TEST_INVALID_STATE`, `ERR_RETEST_WINDOW_EXPIRED`, `ERR_WATER_TEST_HOLD_TIME_EXCEEDED`, `ERR_CONFIRMATORY_SAME_OFFICER`, `ERR_VALIDATION`, `ERR_INVALID_TIMESTAMP`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_RETEST_CONFIRMED_POSITIVE`.

**`POST /water-service/water-tests/{water_test_id}/lapse-retest-window`** — latches a presumptive positive whose retest window closed with no confirmatory sample.
- Roles: `ComplianceOfficer`, `PlatformAdmin`. Success: 200, the updated `WaterTest` in `CONFIRMED_POSITIVE`.
- Request: no body.
- Errors: `ERR_WATER_TEST_NOT_FOUND`, `ERR_WATER_TEST_INVALID_STATE`, `ERR_RETEST_WINDOW_STILL_OPEN`.

**`GET /water-service/water-tests/{water_test_id}/treatment-recommendations`** — recommendations founded on this test.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Estimator`, `CustomerContact`. Success: 200, an array of `TreatmentRecommendation`.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WATER_TEST_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

### 4.10. Treatment Recommendations

**`GET /water-service/treatment-recommendations/{treatment_recommendation_id}`** — reads one recommendation including its as-of `status_effective`.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Estimator`, `CustomerContact`. Success: 200, the `TreatmentRecommendation`. No ownership check.
- Request: no body.
- Errors: `ERR_TREATMENT_RECOMMENDATION_NOT_FOUND`.

**`GET /water-service/treatment-recommendations`** — lists recommendations, including superseded chains.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Estimator`, `CustomerContact`. Success: 200, an array of `TreatmentRecommendation`.
- Request: optional filters `well_profile_id`, `water_test_id`, `superseded_by_id`, `status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/treatment-recommendations/{treatment_recommendation_id}/accept`** — the customer accepts, installing the media and rewiring both maintenance clocks.
- Roles: `CustomerContact`. Success: 200, the updated `TreatmentRecommendation` in `ACCEPTED`.
- Request: no body.
- Errors: `ERR_TREATMENT_RECOMMENDATION_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_TREATMENT_RECOMMENDATION_INVALID_STATE`, `ERR_POTABILITY_PENDING_CONFIRMATION`, `ERR_TREATMENT_RECOMMENDATION_EXPIRED`.

### 4.11. Quotes

**`POST /water-service/quotes`** — creates a `DRAFT` quote against a cited inspection, whose state is not examined here.
- Roles: `Estimator`, `PlatformAdmin`. Success: 201, the created `Quote` with every money field 0.
- Request: `property_id`, `well_profile_id`, `inspection_id`, `scope`, `estimated_labor_minutes`, `estimated_start_at`, `quoted_technician_tier`.
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_INVALID_TIMESTAMP`, `ERR_PROPERTY_NOT_FOUND`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`.

**`GET /water-service/quotes/{quote_id}`** — reads one quote.
- Roles: `PlatformAdmin`, `Estimator`, `Dispatcher`, `BillingClerk`, `CustomerContact`. Success: 200, the `Quote`. Ownership is enforced for `CustomerContact`.
- Request: no body.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`.

**`GET /water-service/quotes`** — lists quotes.
- Roles: `PlatformAdmin`, `Estimator`, `Dispatcher`, `BillingClerk`. Success: 200, an array of `Quote`.
- Request: optional filters `property_id`, `well_profile_id`, `inspection_id`, `status`, `scope`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/quotes/{quote_id}/lines`** — adds a line to a `DRAFT` or `REVISION_REQUIRED` quote; carries concurrency control on the quote.
- Roles: `Estimator`. Success: 201, the created `QuoteLine` in `ACTIVE` with `origin` `ESTIMATOR`.
- Request: `part_catalog_item_id`, `quantity`, `expected_quote_version`.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_QUOTE_INVALID_STATE`, `ERR_STALE_QUOTE_VERSION`, `ERR_VALIDATION`, `ERR_NEGATIVE_QUANTITY`, `ERR_PART_CATALOG_ITEM_NOT_FOUND`, `ERR_PART_DISCONTINUED`, `ERR_QUANTITY_EXCEEDS_LIMIT`, `ERR_INSPECTION_REQUIRED`, `ERR_YIELD_INSUFFICIENT_FOR_PUMP`.

**`GET /water-service/quotes/{quote_id}/lines`** — every line of this quote.
- Roles: `PlatformAdmin`, `Estimator`, `Dispatcher`, `BillingClerk`, `CustomerContact`. Success: 200, an array of `QuoteLine`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

**`POST /water-service/quotes/{quote_id}/price`** — prices the quote, pinning catalog costs onto every `ACTIVE` line.
- Roles: `Estimator`. Success: 200, the updated `Quote` in `PRICED`.
- Request: no body.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_QUOTE_INVALID_STATE`, `ERR_QUOTE_HAS_NO_ACTIVE_LINES`.

**`POST /water-service/quotes/{quote_id}/send`** — sends a `PRICED` quote and stamps `sent_at`.
- Roles: `Estimator`. Success: 200, the updated `Quote` in `SENT`.
- Request: no body.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_QUOTE_INVALID_STATE`.

**`POST /water-service/quotes/{quote_id}/approve`** — the customer approves a `SENT` quote. A failed yield gate writes durably and *then* errors.
- Roles: `CustomerContact`. Success: 200, the updated `Quote` in `APPROVED` with `approved_at` and `approved_total_cents` set.
- Request: no body.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_QUOTE_INVALID_STATE`, `ERR_INSPECTION_STALE`, `ERR_ACCOUNT_ON_CREDIT_HOLD`, `ERR_QUOTE_LINE_YIELD_EXCEEDED`.

**`POST /water-service/quotes/{quote_id}/decline`** — the customer declines a `SENT` quote.
- Roles: `CustomerContact`. Success: 200, the updated `Quote` in `DECLINED`.
- Request: no body.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_QUOTE_INVALID_STATE`.

**`POST /water-service/quotes/{quote_id}/expire`** — expires a `SENT` quote whose 30-day validity window has closed.
- Roles: `PlatformAdmin`. Success: 200, the updated `Quote` in `EXPIRED`.
- Request: no body.
- Errors: `ERR_QUOTE_NOT_FOUND`, `ERR_QUOTE_INVALID_STATE`.

### 4.12. Quote Lines

**`GET /water-service/quote-lines/{quote_line_id}`** — reads one quote line.
- Roles: `PlatformAdmin`, `Estimator`, `Dispatcher`, `BillingClerk`, `CustomerContact`. Success: 200, the `QuoteLine`. No ownership check.
- Request: no body.
- Errors: `ERR_QUOTE_LINE_NOT_FOUND`.

**`GET /water-service/quote-lines`** — lists quote lines, including supersede chains.
- Roles: `PlatformAdmin`, `Estimator`, `Dispatcher`, `BillingClerk`. Success: 200, an array of `QuoteLine`.
- Request: optional filters `quote_id`, `part_catalog_item_id`, `superseded_by_line_id`, `status`, `origin`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`DELETE /water-service/quote-lines/{quote_line_id}`** — removes an `ACTIVE` line from a `DRAFT` or `REVISION_REQUIRED` quote.
- Roles: `Estimator`. Success: 200, the updated `QuoteLine` in `REMOVED`; both the line's and the quote's `version` rise by 1.
- Request: no body.
- Errors: `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_QUOTE_LINE_INVALID_STATE`.

### 4.13. Emergency Tickets

**`POST /water-service/emergency-tickets`** — intake of a no-water emergency; latches the membership tier and stamps `intake_at`.
- Roles: `Dispatcher`, `PlatformAdmin`. Success: 201, the created `EmergencyTicket` at `INTAKE` / `NOT_REQUIRED`.
- Request: `property_id`, `well_profile_id`, `account_id`, `reported_outage_hours`.
- Errors: `ERR_VALIDATION`, `ERR_PROPERTY_NOT_FOUND`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`.

**`GET /water-service/emergency-tickets/{emergency_ticket_id}`** — reads one ticket, both axes.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`, `CustomerContact`. Success: 200, the `EmergencyTicket`. Ownership is enforced for `CustomerContact`.
- Request: no body.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`.

**`GET /water-service/emergency-tickets`** — lists tickets with dual-axis filters.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`. Success: 200, an array of `EmergencyTicket`.
- Request: optional filters `property_id`, `well_profile_id`, `account_id`, `assigned_technician_id`, `dispatch_status`, `authorization_status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/triage`** — triages the ticket; refuses an out-of-area property.
- Roles: `Dispatcher`. Success: 200, the updated ticket at `TRIAGED`.
- Request: no body.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_EMERGENCY_DISPATCH_INVALID_STATE`, `ERR_OUT_OF_SERVICE_AREA`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/dispatch`** — assigns an available technician, stamps `dispatched_at` and computes `response_minutes`.
- Roles: `Dispatcher`. Success: 200, the updated ticket at `DISPATCHED`.
- Request: `technician_id`.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_EMERGENCY_DISPATCH_INVALID_STATE`, `ERR_VALIDATION`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_TECHNICIAN_UNAVAILABLE`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/arrive`** — the assigned technician marks arrival on site.
- Roles: `Technician`. Success: 200, the updated ticket at `ON_SITE`.
- Request: no body.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_EMERGENCY_DISPATCH_INVALID_STATE`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/diagnosis`** — records the cause and the on-site estimate, computes the severity chain and moves the authorisation axis.
- Roles: `Technician`. Success: 200, the updated ticket at `DIAGNOSED`, with the authorisation axis now `PRE_AUTHORIZED` or `PENDING`.
- Request: `cause_class`, `onsite_estimate_cents`.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_EMERGENCY_DISPATCH_INVALID_STATE`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/authorize`** — the customer authorises work above the pre-authorisation cap.
- Roles: `CustomerContact`. Success: 200, the updated ticket with authorisation `AUTHORIZED`.
- Request: no body.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_EMERGENCY_AUTH_INVALID_STATE`, `ERR_ACCOUNT_ON_CREDIT_HOLD`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/decline-authorization`** — the customer refuses the estimate.
- Roles: `CustomerContact`. Success: 200, the updated ticket with authorisation `DECLINED`.
- Request: no body.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_EMERGENCY_AUTH_INVALID_STATE`.

**`POST /water-service/emergency-tickets/{emergency_ticket_id}/cancel`** — closes a ticket that will not be served.
- Roles: `Dispatcher`, `PlatformAdmin`. Success: 200, the updated ticket at `CANCELLED`. Available from `INTAKE`, from `TRIAGED`, and from `DIAGNOSED` only when authorisation is `DECLINED`.
- Request: no body.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_EMERGENCY_DISPATCH_INVALID_STATE`.

**`GET /water-service/emergency-tickets/{emergency_ticket_id}/work-orders`** — the work order founded on this ticket.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`, `CustomerContact`. Success: 200, an array of `WorkOrder`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

### 4.14. Work Orders

**`POST /water-service/work-orders`** — creates a `DRAFT` work order from exactly one of an approved quote or an emergency ticket, whose own dispatch state is not examined.
- Roles: `Dispatcher`, `PlatformAdmin`. Success: 201, the created `WorkOrder` at `DRAFT` / `NOT_BILLABLE` with `pipeline` derived.
- Request: `property_id`, `well_profile_id`, `assigned_technician_id`, `scope`, and exactly one of optional `quote_id` or optional `emergency_ticket_id`.
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_PROPERTY_NOT_FOUND`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_EMERGENCY_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_ORIGIN_CONFLICT`, `ERR_QUOTE_NOT_APPROVED`, `ERR_EMERGENCY_TICKET_ALREADY_LINKED`.

**`GET /water-service/work-orders/{work_order_id}`** — reads one work order, both axes.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `Estimator`, `BillingClerk`, `ComplianceOfficer`, `CustomerContact`. Success: 200, the `WorkOrder`. Ownership is enforced for `CustomerContact` and `Technician`.
- Request: no body.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`.

**`GET /water-service/work-orders`** — lists work orders with dual-axis filters.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `Estimator`, `BillingClerk`, `ComplianceOfficer`. Success: 200, an array of `WorkOrder`.
- Request: optional filters `property_id`, `well_profile_id`, `quote_id`, `emergency_ticket_id`, `assigned_technician_id`, `origin_callback_claim_id`, `pipeline`, `fulfillment_status`, `billing_status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/work-orders/{work_order_id}/schedule`** — books the work order, enforcing the permit prerequisite, the tier gate and both capacity rules. Also the path back from `HELD`.
- Roles: `Dispatcher`. Success: 200, the updated `WorkOrder` at `SCHEDULED` with `hold_reason` cleared.
- Request: `scheduled_start_at`, `scheduled_end_at`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`, `ERR_PERMIT_REQUIRED_NOT_APPROVED`, `ERR_TECHNICIAN_TIER_INSUFFICIENT`, `ERR_VALIDATION`, `ERR_INVALID_TIMESTAMP`, `ERR_INVALID_DATE_RANGE`, `ERR_TECHNICIAN_SCHEDULE_CONFLICT`, `ERR_WELL_SERVICE_WINDOW_CONFLICT`.

**`POST /water-service/work-orders/{work_order_id}/start`** — the assigned technician starts the work and stamps `actual_start_at`.
- Roles: `Technician`. Success: 200, the updated `WorkOrder` at `IN_PROGRESS`.
- Request: no body.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`.

**`POST /water-service/work-orders/{work_order_id}/parts-consumption`** — posts a consumption row and decrements stock immediately.
- Roles: `Technician`. Success: 201, the created `PartsConsumptionEntry` in `POSTED`.
- Request: `part_catalog_item_id`, `quantity`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`, `ERR_VALIDATION`, `ERR_NEGATIVE_QUANTITY`, `ERR_PART_CATALOG_ITEM_NOT_FOUND`, `ERR_NON_WELL_CAUSE_BLOCKS_PARTS`, `ERR_AUTHORIZATION_REQUIRED`, `ERR_PART_DISCONTINUED`, `ERR_QUANTITY_EXCEEDS_LIMIT`, `ERR_PART_OUT_OF_STOCK`, `ERR_PREAUTH_CAP_EXCEEDED`.

**`GET /water-service/work-orders/{work_order_id}/parts-consumption`** — consumption rows of this work order.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`. Success: 200, an array of `PartsConsumptionEntry`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

**`POST /water-service/work-orders/{work_order_id}/complete`** — completes the work order and fires the eight-hop cascade.
- Roles: `Technician`. Success: 200, the updated `WorkOrder` at `COMPLETED` / `PENDING_INVOICE`.
- Request: `actual_labor_minutes`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`, `ERR_VALIDATION`, `ERR_AUTHORIZATION_REQUIRED`.

**`POST /water-service/work-orders/{work_order_id}/cancel`** — cancels the work order; from `IN_PROGRESS` this reverses every posted consumption row and restores stock.
- Roles: `Dispatcher`, `PlatformAdmin`. Success: 200, the updated `WorkOrder` at `CANCELLED`.
- Request: no body.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`.

**`POST /water-service/work-orders/{work_order_id}/write-off`** — writes off a cancelled work order on the billing axis.
- Roles: `BillingClerk`. Success: 200, the updated `WorkOrder` at `WRITTEN_OFF`.
- Request: no body. The billing axis is checked before the fulfilment axis.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_WORK_ORDER_INVALID_BILLING_STATE`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`.

**`GET /water-service/work-orders/{work_order_id}/warranty-coverages`** — coverages minted by this work order.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`, `CustomerContact`. Success: 200, an array of `WarrantyCoverage`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

**`POST /water-service/work-orders/{work_order_id}/callback-claims`** — the customer raises a warranty callback. An out-of-window coverage still records the claim durably and *then* errors.
- Roles: `CustomerContact`. Success: 201, the created `CallbackClaim` in `SUBMITTED`.
- Request: `warranty_coverage_id`, `complaint_class`, `description`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_WARRANTY_COVERAGE_NOT_FOUND`, `ERR_CALLBACK_ALREADY_CONSUMED`, `ERR_CALLBACK_OUT_OF_WARRANTY`.

**`GET /water-service/work-orders/{work_order_id}/callback-claims`** — claims raised against this work order, including durably recorded rejected ones.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`, `CustomerContact`. Success: 200, an array of `CallbackClaim`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

**`GET /water-service/work-orders/{work_order_id}/invoices`** — invoices constructed from this work order, one per `ACTIVE` shared-well share.
- Roles: `PlatformAdmin`, `Dispatcher`, `BillingClerk`, `CustomerContact`. Success: 200, an array of `Invoice`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

**`GET /water-service/work-orders/{work_order_id}/maintenance-visits`** — visits produced by this work order's completion.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`. Success: 200, an array of `MaintenanceVisit`.
- Request: optional `limit` and `offset`.
- Errors: `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

### 4.15. Parts Consumption Entries

**`GET /water-service/parts-consumption-entries/{parts_consumption_entry_id}`** — reads one consumption entry.
- Roles: `PlatformAdmin`, `Technician`, `BillingClerk`, `Dispatcher`. Success: 200, the `PartsConsumptionEntry`.
- Request: no body.
- Errors: `ERR_PARTS_CONSUMPTION_ENTRY_NOT_FOUND`.

**`GET /water-service/parts-consumption-entries`** — lists consumption entries.
- Roles: `PlatformAdmin`, `Technician`, `BillingClerk`, `Dispatcher`. Success: 200, an array of `PartsConsumptionEntry`.
- Request: optional filters `work_order_id`, `part_catalog_item_id`, `status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

### 4.16. Warranty Coverages

**`GET /water-service/warranty-coverages/{warranty_coverage_id}`** — reads one coverage including its as-of `coverage_state`.
- Roles: `PlatformAdmin`, `Technician`, `BillingClerk`, `Dispatcher`, `CustomerContact`. Success: 200, the `WarrantyCoverage`. No ownership check.
- Request: no body.
- Errors: `ERR_WARRANTY_COVERAGE_NOT_FOUND`.

**`GET /water-service/warranty-coverages`** — lists coverages, including supersede chains.
- Roles: `PlatformAdmin`, `Technician`, `BillingClerk`, `Dispatcher`. Success: 200, an array of `WarrantyCoverage`.
- Request: optional filters `work_order_id`, `parts_consumption_entry_id`, `superseded_by_id`, `coverage_class`, `status`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/warranty-coverages/{warranty_coverage_id}/void`** — voids an `ACTIVE` coverage.
- Roles: `PlatformAdmin`. Success: 200, the updated `WarrantyCoverage` in `VOIDED`.
- Request: no body.
- Errors: `ERR_WARRANTY_COVERAGE_NOT_FOUND`, `ERR_WARRANTY_ALREADY_SUPERSEDED`.

### 4.17. Callback Claims

**`GET /water-service/callback-claims/{callback_claim_id}`** — reads one callback claim.
- Roles: `PlatformAdmin`, `Technician`, `Dispatcher`, `BillingClerk`, `CustomerContact`. Success: 200, the `CallbackClaim`. No ownership check.
- Request: no body.
- Errors: `ERR_CALLBACK_CLAIM_NOT_FOUND`.

**`GET /water-service/callback-claims`** — lists callback claims.
- Roles: `PlatformAdmin`, `Technician`, `Dispatcher`, `BillingClerk`. Success: 200, an array of `CallbackClaim`.
- Request: optional filters `warranty_coverage_id`, `original_work_order_id`, `remedy_work_order_id`, `status`, `complaint_class`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/callback-claims/{callback_claim_id}/adjudicate`** — a technician other than the one who completed the original work order reviews, approves or rejects the claim.
- Roles: `Technician`. Success: 200, the updated `CallbackClaim`.
- Request: `decision`, one of `REVIEW`, `APPROVE` or `REJECT`.
- Errors: `ERR_CALLBACK_CLAIM_NOT_FOUND`, `ERR_CALLBACK_CLAIM_INVALID_STATE`, `ERR_CALLBACK_ADJUDICATOR_CONFLICT`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_CALLBACK_LIMIT_REACHED`.

**`POST /water-service/callback-claims/{callback_claim_id}/remedy-work-order`** — raises the remedy work order for an approved claim.
- Roles: `Dispatcher`. Success: 201, the created `WorkOrder` in `DRAFT` with `origin_callback_claim_id` set, `pipeline` `SCHEDULED`, and `quote_id` and `emergency_ticket_id` null.
- Request: `assigned_technician_id`, `scope`.
- Errors: `ERR_CALLBACK_CLAIM_NOT_FOUND`, `ERR_CALLBACK_CLAIM_INVALID_STATE`, `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_TECHNICIAN_NOT_FOUND`.

### 4.18. Permits

**`POST /water-service/permits`** — creates a `DRAFT` permit against a well, optionally linked to a quote and a work order.
- Roles: `ComplianceOfficer`, `Estimator`, `PlatformAdmin`. Success: 201, the created `Permit` with `fee_cents` 0 and `filed_at` null.
- Request: `well_profile_id`, `jurisdiction_code`, `scope`, optional `quote_id` (default null), optional `work_order_id` (default null), optional `expedited` (default `false`), optional `post_hoc` (default `false`).
- Errors: `ERR_VALIDATION`, `ERR_INVALID_ENUM`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`.

**`GET /water-service/permits/{permit_id}`** — reads one permit.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Estimator`, `Dispatcher`, `BillingClerk`. Success: 200, the `Permit`.
- Request: no body.
- Errors: `ERR_PERMIT_NOT_FOUND`.

**`GET /water-service/permits`** — lists permits.
- Roles: `PlatformAdmin`, `ComplianceOfficer`, `Estimator`, `Dispatcher`, `BillingClerk`. Success: 200, an array of `Permit`.
- Request: optional filters `well_profile_id`, `work_order_id`, `quote_id`, `mandated_alternate_part_id`, `superseded_quote_line_id`, `status`, `jurisdiction_code`, `scope`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/permits/{permit_id}/file`** — files the permit with the well's jurisdiction and computes the fee.
- Roles: `ComplianceOfficer`. Success: 200, the updated `Permit` in `FILED` with `jurisdiction_tier`, `fee_cents` and `filed_at` set.
- Request: no body.
- Errors: `ERR_PERMIT_NOT_FOUND`, `ERR_PERMIT_INVALID_STATE`, `ERR_PERMIT_JURISDICTION_MISMATCH`, `ERR_POST_HOC_PERMIT_WINDOW_EXPIRED`, `ERR_PERMIT_ALREADY_ON_FILE`.

**`POST /water-service/permits/{permit_id}/approve`** — approves a `FILED` permit, optionally imposing a mandated alternate part and firing the four-hop cascade.
- Roles: `ComplianceOfficer`. Success: 200, the updated `Permit` in `APPROVED` or `APPROVED_WITH_CONDITIONS`.
- Request: optional `mandated_alternate_part_id`, optional `superseded_quote_line_id`, optional `condition_text` — all three defaulting to null. The first two are supplied together or not at all, and exactly one of them alone is `ERR_VALIDATION`; a `condition_text` sent without them is discarded.
- Errors: `ERR_PERMIT_NOT_FOUND`, `ERR_PERMIT_INVALID_STATE`, `ERR_VALIDATION`, `ERR_PART_CATALOG_ITEM_NOT_FOUND`, `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_QUOTE_LINE_INVALID_STATE`, `ERR_PART_DISCONTINUED`, `ERR_PART_CATEGORY_MISMATCH`.

**`POST /water-service/permits/{permit_id}/reject`** — rejects a `FILED` permit.
- Roles: `ComplianceOfficer`. Success: 200, the updated `Permit` in `REJECTED`.
- Request: no body.
- Errors: `ERR_PERMIT_NOT_FOUND`, `ERR_PERMIT_INVALID_STATE`.

**`POST /water-service/permits/{permit_id}/refile-draft`** — returns a `REJECTED` permit to `DRAFT`, clearing `filed_at` and resetting `fee_cents` to 0.
- Roles: `ComplianceOfficer`. Success: 200, the updated `Permit` in `DRAFT`.
- Request: no body.
- Errors: `ERR_PERMIT_NOT_FOUND`, `ERR_PERMIT_INVALID_STATE`.

**`POST /water-service/permits/{permit_id}/withdraw`** — withdraws a `FILED` permit.
- Roles: `ComplianceOfficer`. Success: 200, the updated `Permit` in `WITHDRAWN`.
- Request: no body.
- Errors: `ERR_PERMIT_NOT_FOUND`, `ERR_PERMIT_INVALID_STATE`.

### 4.19. Maintenance Plans

**`POST /water-service/maintenance-plans`** — creates a recurring maintenance plan on a well, freezing `interval_days_as_designed`.
- Roles: `PlatformAdmin`, `Dispatcher`. Success: 201, the created `MaintenancePlan` in `ACTIVE` / `COMPLIANT`.
- Request: `well_profile_id`, `account_id`.
- Errors: `ERR_VALIDATION`, `ERR_WELL_PROFILE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PLAN_ALREADY_EXISTS_FOR_WELL`.

**`GET /water-service/maintenance-plans/{maintenance_plan_id}`** — reads one plan, both axes and both clocks.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`, `CustomerContact`. Success: 200, the `MaintenancePlan`. No ownership check.
- Request: no body.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`.

**`GET /water-service/maintenance-plans`** — lists plans.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `BillingClerk`. Success: 200, an array of `MaintenancePlan`.
- Request: optional filters `well_profile_id`, `account_id`, `status`, `compliance_state`, `filter_media`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`POST /water-service/maintenance-plans/{maintenance_plan_id}/salt-deliveries`** — records a salt delivery and resets the consumption clock; carries concurrency control on the plan.
- Roles: `Dispatcher`, `Technician`, `PlatformAdmin`. Success: 200, the updated `MaintenancePlan`.
- Request: `delivered_lbs`, `expected_maintenance_plan_version`.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_MAINTENANCE_PLAN_INVALID_STATE`, `ERR_STALE_MAINTENANCE_PLAN_VERSION`, `ERR_VALIDATION`, `ERR_NEGATIVE_QUANTITY`, `ERR_SALT_DELIVERY_EXCEEDS_CAPACITY`.

**`POST /water-service/maintenance-plans/{maintenance_plan_id}/filter-change`** — records a filter media change and resets the time-driven clock.
- Roles: `Technician`, `Dispatcher`, `PlatformAdmin`. Success: 200, the updated `MaintenancePlan`.
- Request: no body.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_MAINTENANCE_PLAN_INVALID_STATE`, `ERR_FILTER_CHANGE_TOO_SOON`.

**`POST /water-service/maintenance-plans/{maintenance_plan_id}/evaluate-compliance`** — runs the compliance evaluation that latches an overdue plan.
- Roles: `PlatformAdmin`. Success: 200, the updated `MaintenancePlan`; when the clock is strictly past `next_due_at` the compliance axis becomes `OVERDUE` and `overdue_latched_at` is stamped.
- Request: no body.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_MAINTENANCE_PLAN_INVALID_STATE`.

**`POST /water-service/maintenance-plans/{maintenance_plan_id}/suspend`** — suspends an `ACTIVE` plan.
- Roles: `PlatformAdmin`. Success: 200, the updated `MaintenancePlan` in `SUSPENDED`.
- Request: no body.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_MAINTENANCE_PLAN_INVALID_STATE`.

**`POST /water-service/maintenance-plans/{maintenance_plan_id}/resume`** — returns a `SUSPENDED` plan to `ACTIVE` and recomputes the operated interval and `next_due_at`.
- Roles: `PlatformAdmin`. Success: 200, the updated `MaintenancePlan` in `ACTIVE`.
- Request: no body.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_MAINTENANCE_PLAN_INVALID_STATE`.

**`POST /water-service/maintenance-plans/{maintenance_plan_id}/terminate`** — terminates a `SUSPENDED` plan.
- Roles: `PlatformAdmin`. Success: 200, the updated `MaintenancePlan` in `TERMINATED`.
- Request: no body.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_MAINTENANCE_PLAN_INVALID_STATE`.

**`GET /water-service/maintenance-plans/{maintenance_plan_id}/visits`** — visits recorded against this plan.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`, `CustomerContact`. Success: 200, an array of `MaintenanceVisit`. No ownership check.
- Request: optional `limit` and `offset`.
- Errors: `ERR_MAINTENANCE_PLAN_NOT_FOUND`, `ERR_INVALID_PAGINATION`.

### 4.20. Maintenance Visits

**`GET /water-service/maintenance-visits/{maintenance_visit_id}`** — reads one maintenance visit.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`. Success: 200, the `MaintenanceVisit`, which carries `id` and `created_at` but no `updated_at` and no `version`.
- Request: no body.
- Errors: `ERR_MAINTENANCE_VISIT_NOT_FOUND`.

**`GET /water-service/maintenance-visits`** — lists maintenance visits.
- Roles: `PlatformAdmin`, `Dispatcher`, `Technician`. Success: 200, an array of `MaintenanceVisit`.
- Request: optional filters `maintenance_plan_id`, `work_order_id`, `visit_kind`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

### 4.21. Invoices

**`GET /water-service/invoices/{invoice_id}`** — reads one invoice.
- Roles: `PlatformAdmin`, `BillingClerk`, `Dispatcher`, `CustomerContact`. Success: 200, the `Invoice`. Ownership is enforced for `CustomerContact`.
- Request: no body.
- Errors: `ERR_INVOICE_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`.

**`GET /water-service/invoices`** — lists invoices.
- Roles: `PlatformAdmin`, `BillingClerk`, `Dispatcher`. Success: 200, an array of `Invoice`.
- Request: optional filters `account_id`, `work_order_id`, `status`, `variant`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

**`GET /water-service/invoices/{invoice_id}/lines`** — the constructed lines of this invoice, ordered by `sequence_no` ascending.
- Roles: `PlatformAdmin`, `BillingClerk`, `Dispatcher`, `CustomerContact`. Success: 200, an array of `InvoiceLine`. Ownership is enforced for `CustomerContact`.
- Request: optional `limit` and `offset`.
- Errors: `ERR_INVOICE_NOT_FOUND`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_INVALID_PAGINATION`.

**`POST /water-service/invoices/{invoice_id}/issue`** — issues a `DRAFT` invoice, moving money onto the account balance.
- Roles: `BillingClerk`. Success: 200, the updated `Invoice` in `ISSUED` with `issued_at` stamped.
- Request: no body.
- Errors: `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_INVALID_STATE`, `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`.

**`POST /water-service/invoices/{invoice_id}/payments`** — records a payment; carries concurrency control on the invoice.
- Roles: `BillingClerk`. Success: 200, the updated `Invoice` in `PARTIALLY_PAID` or `PAID_IN_FULL`.
- Request: `amount_cents`, `expected_invoice_version`.
- Errors: `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_INVALID_STATE`, `ERR_STALE_INVOICE_VERSION`, `ERR_VALIDATION`, `ERR_NEGATIVE_QUANTITY`, `ERR_PAYMENT_AMOUNT_INVALID`, `ERR_PAYMENT_EXCEEDS_BALANCE`.

**`POST /water-service/invoices/{invoice_id}/void`** — voids an `ISSUED` or `PARTIALLY_PAID` invoice, running the ledger's compensating action.
- Roles: `BillingClerk`. Success: 200, the updated `Invoice` in `VOID` with `amount_paid_cents` left intact as a historical record.
- Request: no body.
- Errors: `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_INVALID_STATE`.

### 4.22. Invoice Lines

**`GET /water-service/invoice-lines/{invoice_line_id}`** — reads one invoice line.
- Roles: `PlatformAdmin`, `BillingClerk`, `CustomerContact`. Success: 200, the `InvoiceLine`, which carries `id` and `created_at` but no `updated_at` and no `version`. No ownership check.
- Request: no body.
- Errors: `ERR_INVOICE_LINE_NOT_FOUND`.

**`GET /water-service/invoice-lines`** — lists invoice lines.
- Roles: `PlatformAdmin`, `BillingClerk`. Success: 200, an array of `InvoiceLine`.
- Request: optional filters `invoice_id`, `parts_consumption_entry_id`, `line_type`, plus `limit` and `offset`.
- Errors: `ERR_INVALID_PAGINATION`.

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ACTOR_SCOPE_VIOLATION` | 403 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_WELL_PROFILE_NOT_FOUND` | 404 |
| `ERR_SHARED_WELL_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_PART_CATALOG_ITEM_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_WATER_TEST_NOT_FOUND` | 404 |
| `ERR_TREATMENT_RECOMMENDATION_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_QUOTE_LINE_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_EMERGENCY_TICKET_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_PARTS_CONSUMPTION_ENTRY_NOT_FOUND` | 404 |
| `ERR_WARRANTY_COVERAGE_NOT_FOUND` | 404 |
| `ERR_CALLBACK_CLAIM_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_PLAN_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_VISIT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVOICE_LINE_NOT_FOUND` | 404 |
| `ERR_INSPECTION_INVALID_STATE` | 409 |
| `ERR_WATER_TEST_INVALID_STATE` | 409 |
| `ERR_TREATMENT_RECOMMENDATION_INVALID_STATE` | 409 |
| `ERR_QUOTE_INVALID_STATE` | 409 |
| `ERR_QUOTE_LINE_INVALID_STATE` | 409 |
| `ERR_EMERGENCY_DISPATCH_INVALID_STATE` | 409 |
| `ERR_EMERGENCY_AUTH_INVALID_STATE` | 409 |
| `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE` | 409 |
| `ERR_WORK_ORDER_INVALID_BILLING_STATE` | 409 |
| `ERR_PERMIT_INVALID_STATE` | 409 |
| `ERR_CALLBACK_CLAIM_INVALID_STATE` | 409 |
| `ERR_INVOICE_INVALID_STATE` | 409 |
| `ERR_MAINTENANCE_PLAN_INVALID_STATE` | 409 |
| `ERR_WARRANTY_ALREADY_SUPERSEDED` | 409 |
| `ERR_PERMIT_JURISDICTION_MISMATCH` | 422 |
| `ERR_POST_HOC_PERMIT_WINDOW_EXPIRED` | 422 |
| `ERR_PERMIT_REQUIRED_NOT_APPROVED` | 422 |
| `ERR_TECHNICIAN_TIER_INSUFFICIENT` | 403 |
| `ERR_RETEST_WINDOW_EXPIRED` | 422 |
| `ERR_WATER_TEST_HOLD_TIME_EXCEEDED` | 422 |
| `ERR_CONFIRMATORY_SAME_OFFICER` | 403 |
| `ERR_CALLBACK_ADJUDICATOR_CONFLICT` | 403 |
| `ERR_STALE_WELL_PROFILE_VERSION` | 412 |
| `ERR_STALE_QUOTE_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_STALE_MAINTENANCE_PLAN_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_TIMESTAMP` | 400 |
| `ERR_NEGATIVE_QUANTITY` | 400 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_CLOCK_BACKWARD` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_NO_TREATMENT_INDICATED` | 422 |
| `ERR_POTABILITY_PENDING_CONFIRMATION` | 422 |
| `ERR_TREATMENT_RECOMMENDATION_EXPIRED` | 422 |
| `ERR_RETEST_WINDOW_STILL_OPEN` | 409 |
| `ERR_YIELD_INSUFFICIENT_FOR_PUMP` | 422 |
| `ERR_INSPECTION_REQUIRED` | 422 |
| `ERR_INSPECTION_STALE` | 422 |
| `ERR_QUOTE_HAS_NO_ACTIVE_LINES` | 422 |
| `ERR_QUOTE_LINE_YIELD_EXCEEDED` | 409 |
| `ERR_QUOTE_NOT_APPROVED` | 422 |
| `ERR_WORK_ORDER_ORIGIN_CONFLICT` | 422 |
| `ERR_EMERGENCY_TICKET_ALREADY_LINKED` | 409 |
| `ERR_TECHNICIAN_UNAVAILABLE` | 409 |
| `ERR_TECHNICIAN_SCHEDULE_CONFLICT` | 409 |
| `ERR_WELL_SERVICE_WINDOW_CONFLICT` | 409 |
| `ERR_NON_WELL_CAUSE_BLOCKS_PARTS` | 422 |
| `ERR_AUTHORIZATION_REQUIRED` | 402 |
| `ERR_PREAUTH_CAP_EXCEEDED` | 402 |
| `ERR_PART_DISCONTINUED` | 422 |
| `ERR_PART_OUT_OF_STOCK` | 409 |
| `ERR_PART_CATEGORY_MISMATCH` | 422 |
| `ERR_QUANTITY_EXCEEDS_LIMIT` | 422 |
| `ERR_CALLBACK_OUT_OF_WARRANTY` | 409 |
| `ERR_CALLBACK_ALREADY_CONSUMED` | 409 |
| `ERR_CALLBACK_LIMIT_REACHED` | 409 |
| `ERR_PERMIT_ALREADY_ON_FILE` | 409 |
| `ERR_OUT_OF_SERVICE_AREA` | 422 |
| `ERR_PAYMENT_AMOUNT_INVALID` | 400 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_ACCOUNT_ON_CREDIT_HOLD` | 402 |
| `ERR_DUPLICATE_SHARED_WELL_AGREEMENT` | 409 |
| `ERR_SHARED_WELL_SPLIT_INVALID` | 422 |
| `ERR_SALT_DELIVERY_EXCEEDS_CAPACITY` | 422 |
| `ERR_FILTER_CHANGE_TOO_SOON` | 422 |
| `ERR_PLAN_ALREADY_EXISTS_FOR_WELL` | 409 |
| `ERR_RETEST_CONFIRMED_POSITIVE` | 422 |

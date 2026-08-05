# Vector & Rodent Control Program API — Product Requirements Document

## 1. Introduction

Municipal vector and rodent control is one of the few public-health programs where a single unanswered phone call can become a neighbourhood-wide infestation. Today the program's work — complaint intake, field inspection, harborage and attractant assessment, abatement orders, statutory owner notice, re-inspection, city abatement and cost recovery — is tracked across three disconnected systems and a shared spreadsheet. Officers cannot see whether the parcel in front of them is a first-time nuisance or a chronic offender; supervisors cannot tell whether a zone has quietly crossed into hotspot conditions; and the finance desk routinely bills owners for work whose recorded labour hours changed after the invoice was drafted.

This document specifies the replacement: a single REST service, mounted under `/vector-control`, that carries a complaint from the moment it is taken over the counter to the moment the last dollar of a cost-recovery lien is released. The service is deliberately opinionated about two things. First, **evidence drives enforcement**: an abatement order may only be issued from an inspection that was actually completed and actually found a violation, and the severity of that violation — captured as a harborage/attractant/sanitation assessment — determines both the compliance window the owner receives and the standard cost the city will bill if it has to do the work itself. Second, **no one signs their own homework**: the supervisor who issues an order may not be the officer who inspected the parcel, a re-inspection may not be run by the officer whose visit produced the order, and the finance officer who prepares an invoice may never be the administrator who approves it.

Because the program's downstream behaviour is driven by aggregates that change constantly — a zone's rodent index, a parcel's chronic score, an owner's outstanding balance — the service recomputes those aggregates from scratch on every relevant mutation rather than patching them incrementally, and it exposes an explicit `version` on the entities that matter so that a client working from a stale read is told so rather than silently overwriting a colleague's judgement. All time in the system is read from a server-held logical clock so that deadlines, surveillance windows and past-due tests are reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. Personnel, Identity and Role-Based Access Control

Every request to every endpoint — including read endpoints and the clock endpoint — must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. Six roles are recognised, and their names are matched exactly as spelled here: `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `FinanceOfficer`, and `PropertyOwner`. If either header is absent, or if `X-User-Role` carries a value that is not one of those six strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration. If both headers are well formed but the named role is not among the roles authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

Three of the six roles are **entity-backed**, meaning `X-User-ID` names a row that already exists in the system. When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Officer`; ownership and segregation-of-duties checks on any resource that references an officer compare that resource's officer foreign key to `X-User-ID`. When `X-User-Role` is `Inspector`, `X-User-ID` is likewise the `id` of the acting `Officer`, and any operation performed on an inspection compares the inspection's `officer_id` to `X-User-ID`. When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting `PropertyOwner` record, and ownership checks compare the `owner_id` carried by the parcel or invoice being touched to `X-User-ID`.

A deliberate subtlety governs officers: an `Officer` record carries a `rank` of either `FIELD_INSPECTOR` or `SUPERVISOR`, but that rank is descriptive only. It labels the officer's duties on printed rosters and is **not** enforced against `X-User-Role`. Any officer `id` may be presented as `Inspector` or as `Supervisor`; every access decision is made by the endpoint's authorised-role list, by the ownership rule above, and by the segregation-of-duties rules of §2.8 — never by comparing `rank` to the header.

The remaining three roles are **opaque**. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires it — for example as `approved_by_user_id` on a cost-recovery invoice — but never compares it to any entity's `id`. When `X-User-Role` is `IntakeClerk`, `X-User-ID` is similarly an opaque operator identifier, recorded nowhere in particular and never matched against an entity `id`. When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is an opaque operator identifier that the server stores as `prepared_by_user_id` on any invoice that officer prepares, and later compares only against the approver's `X-User-ID` to enforce four-eyes approval — never against an entity's `id`.

Ownership enforcement is a distinct failure from role enforcement. When a caller holds a role the endpoint permits but is reaching for someone else's resource — a `PropertyOwner` reading another owner's parcel, invoice or owner record, filing a complaint on a parcel they do not own, or paying an invoice that is not theirs; an `Inspector` starting, completing or attaching an assessment to an inspection assigned to a different officer — the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule guards exactly eight operations: complaint intake, inspection start, inspection completion, assessment recording, invoice payment, the single-owner read, the single-parcel read, and the single-invoice read.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` or `offset` outside those bounds is a request-shape defect and is rejected with `ERR_VALIDATION` (HTTP 400).

Results are always ordered by `created_at` ascending, oldest first, with no alternative sort exposed. For the two child collections whose rows carry no `updated_at` — surveillance readings and assessments — the same `created_at` ascending order applies. Every list response populates `limit`, `offset`, `total_count` and `has_more` inside `meta`: `total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window.

### 2.4. Record Identity, Timestamps and the Program Logical Clock

Every persisted record carries a server-minted `id` in UUID form with no type prefix — a parcel's identifier and an invoice's identifier are indistinguishable in shape — and a `created_at` timestamp. Most records additionally carry an `updated_at` timestamp and an integer `version`. `version` begins at 1 the moment the record is created and increases by exactly 1 on each mutation that the specification says bumps it; `updated_at` is refreshed to the current logical clock on every mutation. Two record types are exceptions and carry only `id` and `created_at`: the harborage/attractant **assessment** attached to an inspection, and the **surveillance reading** attached to a bait station. Neither of those two has an `updated_at` and neither has a `version` — they are append-only observations, never edited.

All timestamps in requests and responses are ISO 8601 UTC strings rendered with exactly three fractional-second digits, for example `2026-05-01T00:00:00.000Z`.

Time is never read from wall-clock. The service holds a single logical clock that reads exactly `2026-05-01T00:00:00Z` at start-up and moves only when a `ProgramAdmin` drives it, supplying the target instant as `to_iso8601`; the response reports both `current_utc` (the new instant) and `previous_utc` (the instant before the move). Moving the clock mutates nothing else: no entity is touched, no aggregate is recomputed, no deadline is re-derived. Every `created_at`, `updated_at`, `triaged_at`, `closed_at`, `started_at`, `completed_at`, `sent_at`, `served_at`, `installed_at`, `reading_at`, `abated_at`, `lien_filed_at`, `voided_at`, `paid_at`, `due_at`, `last_index_recomputed_at`, `last_inspection_at`, `last_reading_at`, `response_due_at` and `compliance_deadline`, and every deadline or window comparison anywhere in this specification, reads that clock.

### 2.5. The Order in Which a Request Is Screened

Requests are screened by a fixed fourteen-step ladder, and the **first** step that fails determines the response. The ordering matters because most write endpoints could fail several of these checks at once, and the test of a correct implementation is which error surfaces.

1. **Authentication.** Both headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED` (401).
2. **Role authorisation.** The acting role appears on the endpoint's authorised list, else `ERR_UNAUTHORIZED` (403).
3. **Existence.** Every resource referenced by the request must exist, checked left to right: the path identifiers first, in the order they appear in the URL, then the foreign keys named in the body, in the order they are listed for that endpoint. The rejection is 404 and names the missing kind — `ERR_ZONE_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_OFFICER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`.
4. **Ownership.** The entity-backed ownership rule of §2.1, else `ERR_NOT_RESOURCE_OWNER` (403).
5. **Request shape.** Required fields present, enum members recognised, integers inside their declared ranges, and the structural window rules honoured, else `ERR_VALIDATION` (400).
6. **Optimistic concurrency.** The supplied parent version matches, else `ERR_STALE_PROPERTY_VERSION` or `ERR_STALE_ORDER_VERSION` (412). See §2.6.
7. **Target state.** The resource being acted on is itself in a status that permits the operation, else `ERR_INVALID_STATE`, `ERR_STATION_DECOMMISSIONED`, `ERR_NOTICE_ALREADY_SERVED` or `ERR_INVOICE_NOT_APPROVED` (409).
8. **Related-entity state.** The other party to the operation is in the state the operation requires, else `ERR_COMPLAINT_NOT_TRIAGED`, `ERR_INSPECTION_NOT_COMPLETED`, `ERR_NO_VIOLATION_FOUND`, `ERR_ORDER_NOT_SERVED` or `ERR_ORDER_NOT_ABATED`.
9. **Segregation of duties and certification currency**, else `ERR_SEGREGATION_OF_DUTIES`, `ERR_REINSPECTION_SAME_OFFICER`, `ERR_SELF_APPROVAL_FORBIDDEN` or `ERR_CERTIFICATION_EXPIRED` (422).
10. **Uniqueness, sequencing and required artefacts**, else `ERR_DUPLICATE_COMPLAINT`, `ERR_ASSESSMENT_ALREADY_EXISTS`, `ERR_ASSESSMENT_REQUIRED`, `ERR_RESULT_KIND_MISMATCH`, `ERR_NOTICE_SEQUENCE_INVALID`, `ERR_INVOICE_ALREADY_EXISTS`, `ERR_EXTENSION_LIMIT_REACHED` or `ERR_DUPLICATE_CODE`.
11. **Officer availability**, else `ERR_OFFICER_SCHEDULE_CONFLICT` (409).
12. **Site and window rules**, else `ERR_PROPERTY_INSPECTION_OVERLAP`, `ERR_REINSPECTION_TOO_EARLY`, `ERR_READING_TOO_SOON`, `ERR_EXTENSION_WINDOW_EXCEEDED` or `ERR_DEADLINE_NOT_PASSED` (409).
13. **Live-enforcement referential rule**, else `ERR_OPEN_ORDER_EXISTS` (409).
14. **Fiscal limits**, else `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_APPROVAL_LIMIT_EXCEEDED` or `ERR_LIEN_THRESHOLD_NOT_MET` (422).

Steps 1, 2 and 5 apply to every endpoint (step 5 to every write endpoint); step 3 applies to every endpoint that takes a path identifier or a foreign key in its body. The narrower steps name their scope where the workflow is described, and the scopes are restated here so no reader has to infer them. Step 6 guards exactly two operations: abatement-order issuance and cost-recovery-invoice preparation. Step 7 guards every state-transition operation. Step 8 guards exactly three: inspection scheduling, order issuance, and invoice preparation. Step 9 guards exactly four: order issuance, inspection scheduling, invoice approval and inspection start. Step 10 guards exactly ten: complaint intake, assessment recording, inspection completion, notice generation, order extension, invoice preparation, zone creation, officer registration, parcel registration and bait-station installation. Step 11 guards inspection scheduling alone. Step 12 guards exactly four: inspection scheduling, station reading recording, order extension and city abatement. Step 13 guards complaint closure alone. Step 14 guards exactly three: invoice payment, invoice approval and lien filing.

### 2.6. Working From a Current Read: Optimistic Concurrency

Two write operations demand that the client prove it was looking at the current state of a parent record when it composed the request.

Issuing an abatement order requires `expected_property_version` in the body — it is not optional — carrying the `version` of the target parcel as the supervisor last observed it. A parcel's `version` advances whenever its chronic score is re-reviewed, whenever its `open_order_count` changes, and whenever a lien is recorded against it; each of those can legitimately change which corrective actions an order ought to demand. If `expected_property_version` does not equal the parcel's current `version`, the issuance is rejected with `ERR_STALE_PROPERTY_VERSION` and HTTP 412, and nothing is written.

Preparing a cost-recovery invoice requires `expected_abatement_order_version` in the body — likewise mandatory — carrying the `version` of the target abatement order as the finance officer last observed it. An order's `version` advances when a replacement invoice supersedes a voided one, when an educational advisory is served on it, and when the abatement crew's recorded hours are revised — each of which changes the amount that may legitimately be billed. If `expected_abatement_order_version` does not equal the order's current `version`, the preparation is rejected with `ERR_STALE_ORDER_VERSION` and HTTP 412.

No other endpoint accepts a version field, and none may be added. Where a request carries neither of these two fields, no concurrency comparison is performed.

### 2.7. Numbers, Rounding and Money

Every score in this system — the complaint priority score, the assessment infestation index, both parcel chronic scores, and the zone rodent index — is carried to exactly two decimal places and rounded half-up. Half-up means a value exactly on the midpoint rounds away from zero, so 12.345 becomes 12.35.

Money is carried in whole cents as integers; no fractional cent exists anywhere in the system. Where a monetary line is derived by multiplying by a rate, the product is rounded half-up to a whole number of cents **at that line**, before that line participates in any later arithmetic. Summing unrounded products and rounding once at the end is a different computation and produces a different bill; §3.7 pins the exact order in which the invoice lines are rounded.

Aggregate counters and aggregate balances are always recomputed from scratch over the qualifying rows after each mutation rather than being patched incrementally. This applies to the owner's `outstanding_balance_cents` and `lifetime_paid_cents`, to a zone's `open_complaint_count`, `chronic_property_count` and `active_station_count`, and to a parcel's `open_order_count`.

### 2.8. Four Eyes on Every Enforcement Step

The program's ordinance requires that enforcement decisions be separated from the evidence that supports them, and the service enforces that structurally rather than by policy reminder.

A supervisor issuing an abatement order may not be the officer who performed the originating inspection: if the issuer's `X-User-ID` equals the `officer_id` of that inspection, the issuance fails with `ERR_SEGREGATION_OF_DUTIES` (422). A re-inspection may not be assigned to the officer whose visit produced the order in the first place: if the `officer_id` on the new visit equals the `officer_id` of the order's originating inspection, scheduling fails with `ERR_REINSPECTION_SAME_OFFICER` (422). An invoice may not be approved by the person who prepared it: if the approver's `X-User-ID` equals the invoice's `prepared_by_user_id`, approval fails with `ERR_SELF_APPROVAL_FORBIDDEN` (422).

Certification currency belongs to the same family of guards. An officer may only begin a field visit while their `certification_expires_at` instant is strictly later than the current logical clock; a clock reading exactly equal to `certification_expires_at`, or later, means the pesticide-applicator certification is void and the start is rejected with `ERR_CERTIFICATION_EXPIRED` (422).

### 2.9. Path Nesting and Resource Reachability

Child collections are reached through their parent's path — assessments through their inspection, notices through their abatement order, readings through their bait station — and path segments are validated strictly left to right. A request for the readings of a station that does not exist fails with `ERR_STATION_NOT_FOUND` before anything about the reading itself is examined. The entity graph itself is flat: complaints, inspections, orders, invoices and stations are peer records linked by explicit identifiers, and each is also reachable through a filtered list rather than only through nesting.

One child table serves two parents. An inspection whose `kind` is `INITIAL` responds to a complaint and carries `complaint_id` populated with `abatement_order_id` null; an inspection whose `kind` is `REINSPECTION` verifies an abatement order and carries `abatement_order_id` populated with `complaint_id` null. The `property_id` on an inspection is never supplied by the caller — it is copied from whichever parent the visit hangs from at scheduling time.

### 2.10. Status Codes and Response Bodies

Creating a new record answers 201 and returns the created record. Every other successful operation — state transitions, payments, reads, list retrievals, and the clock move — answers 200. Operations that mutate a record return the full updated record, so a caller can read the record's new `version` from the response of the call that advanced it.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Program Registry

Before a single complaint can be taken, a `ProgramAdmin` populates four registries: surveillance zones, owners of record, parcels, and officers.

A surveillance zone is created with a human-readable `name` of 1 to 120 characters, a short `code` used on printed reports which must be 2 to 16 uppercase characters and unique across all zones, and a `population_density_per_sqkm` integer of zero or more describing residential density for program reporting. A newly created zone always starts with `posture` `NORMAL`, `rodent_index` 0.00, and its three counters — `open_complaint_count`, `chronic_property_count` and `active_station_count` — all at 0, with `last_index_recomputed_at` null until the first recompute occurs. Attempting to reuse a zone `code` is rejected with `ERR_DUPLICATE_CODE`.

An owner of record is registered with a legal `full_name` of 1 to 120 characters, a contact `email` for electronic notices, and a `mailing_address` that is the address of record used whenever a notice is physically served. Two optional flags accompany the registration. `notice_preference` records the channel the owner prefers and is one of `FIRST_CLASS_MAIL`, `CERTIFIED_MAIL` or `PERSONAL_SERVICE`, defaulting to `CERTIFIED_MAIL` when omitted; it is a record of preference and does not by itself constrain how a notice is actually served. `hardship_certified` marks an owner who holds a certified financial-hardship exemption and defaults to false; it is the sole gate on the hardship discount described in §3.7. Every new owner starts with `outstanding_balance_cents` 0 and `lifetime_paid_cents` 0.

A parcel is registered inside a zone, the payload naming the `zone_id` that contains it and the `owner_id` billed for cost recovery, together with a street `address_line`, an assessor `parcel_number` that must be unique across all parcels (a collision yields `ERR_DUPLICATE_CODE`), and a `property_type` drawn from `RESIDENTIAL_SINGLE`, `RESIDENTIAL_MULTI`, `COMMERCIAL_FOOD`, `COMMERCIAL_OTHER` or `VACANT_LOT`. An optional `unit_count` records the dwelling or tenant units on the parcel; it must be at least 1 and defaults to 1. A new parcel is born at `version` 1 with `chronic_score` 0.00, `provisional_chronic_score` 0.00, `chronic_flag` false, `open_order_count` 0, `lien_encumbered` false and `last_inspection_at` null. Parcels can be listed with optional filters on `zone_id`, on `owner_id` and on `chronic_flag`, and a single parcel read returns its chronic scores, its `open_order_count`, its `lien_encumbered` flag and its current `version` — that last value being what a supervisor must quote when issuing an order.

Officers are registered with a `full_name` printed on notices, a `badge_number` unique across all officers (`ERR_DUPLICATE_CODE` on collision), a descriptive `rank` of `FIELD_INSPECTOR` or `SUPERVISOR`, and a `certification_expires_at` instant marking when the officer's pesticide-applicator certification lapses. The identifier returned by that registration is precisely what an `Inspector` or `Supervisor` presents in `X-User-ID`. Each officer carries an `active_assignment_count` that starts at 0 and tracks how many of their inspections are currently `SCHEDULED` or `IN_PROGRESS`; it rises by one when a visit is booked to them and falls by one when that visit completes.

### 3.2. Taking a Complaint and Triaging It

Complaints reach the program two ways: over the counter or by telephone through an `IntakeClerk`, or directly from a `PropertyOwner` about their own parcel. Intake names the `property_id` the complaint concerns and a `complaint_type` from `RODENT_SIGHTING`, `HARBORAGE`, `GARBAGE_ACCUMULATION`, `DEAD_ANIMAL` or `MOSQUITO_BREEDING`, records who is filing via `reporter_type` — `RESIDENT`, `OWNER`, `AGENCY` or `ANONYMOUS` — and captures a free-text `description` of 1 to 1000 characters. Three optional fields round out the payload: `reporter_name` and `reporter_phone`, both defaulting to null and both routinely omitted for `ANONYMOUS` intake, and `reported_severity`, the severity the caller claims, drawn from `ROUTINE`, `HIGH` or `CRITICAL` and defaulting to `ROUTINE`.

Every complaint is born in status `RECEIVED`. At intake the system copies the parcel's zone onto the complaint as `zone_id` — a value fixed at that moment and never re-derived afterwards, even if the parcel is later reassigned — and sets the operative `severity` equal to `reported_severity`. It then computes `priority_score` and `response_due_at`, increments the zone's `open_complaint_count`, and recomputes that zone's `rodent_index` and `posture`. The complaint's `closure_reason`, `triaged_at` and `closed_at` all begin null.

The program refuses to log the same nuisance twice. If an open complaint of the same `complaint_type` already exists on the same parcel and was created within the last 48 hours of logical-clock time, intake is rejected with `ERR_DUPLICATE_COMPLAINT`. "Open" here means the earlier complaint has not reached any of the four closed statuses.

**Dispatch priority.** The `priority_score` is a weighted sum, evaluated at intake and evaluated again at triage, of four components. The severity base contributes 20 for `ROUTINE`, 40 for `HIGH` and 60 for `CRITICAL`, reading the complaint's operative `severity` and not the reported one. The nuisance-type weight contributes 10 for `RODENT_SIGHTING`, 15 for `HARBORAGE`, 12 for `GARBAGE_ACCUMULATION`, 8 for `DEAD_ANIMAL` and 18 for `MOSQUITO_BREEDING`. A chronic-property bonus of 15 is added when the parcel's `chronic_flag` is true at the moment of the call, and nothing is added when it is false. A posture bonus is added according to the containing zone's `posture` read at that same moment: 0 when `NORMAL`, 5 when `ELEVATED`, and 12 when `HOTSPOT`. The four contributions are added together, the result is capped at a maximum of 100, and the capped value is rounded half-up to two decimal places. Only the one complaint being scored participates: no other complaint on the parcel or in the zone influences the number.

**Response deadline.** The `response_due_at` is the complaint's `created_at` plus a service-level window that depends on the operative `severity`: 168 hours for `ROUTINE`, 72 hours for `HIGH`, and 24 hours for `CRITICAL`. The offset is *always* measured from `created_at` and never from `triaged_at`, so when triage changes the severity the deadline moves relative to the original intake instant rather than relative to the triage instant.

**Triage.** A `Supervisor` triages a complaint that is still in `RECEIVED`, supplying the `severity` they judge correct — one of `ROUTINE`, `HIGH` or `CRITICAL` — and optionally some `triage_notes`. Triaging anything other than a `RECEIVED` complaint is `ERR_INVALID_STATE`. The submitted severity is written first, and then one automatic adjustment applies: if the containing zone's `posture` is `HOTSPOT` at triage time and the resulting severity would be `ROUTINE`, it is escalated to `HIGH`. `HIGH` and `CRITICAL` are left as submitted, and a zone posture of `NORMAL` or `ELEVATED` leaves even `ROUTINE` untouched. With the operative severity settled, both `priority_score` and `response_due_at` are recomputed — the deadline still measured from `created_at` — `triaged_at` is stamped with the current logical clock, and the complaint moves `RECEIVED → TRIAGED`.

**Administrative closure.** A `Supervisor` may also close a complaint outright, supplying a `closure_reason` and an optional `note`. Only two reasons are accepted as input here: `WITHDRAWN`, sending the complaint to `CLOSED_WITHDRAWN`, and `DUPLICATE`, sending it to `CLOSED_DUPLICATE`. The other two reasons, `NO_VIOLATION` and `RESOLVED`, are written exclusively by the system transitions described in §3.5 and §3.7, and supplying either of them as input is rejected with `ERR_VALIDATION`.

Only a complaint still sitting in `RECEIVED` or in `TRIAGED` may be closed this way; once a visit has been booked the case runs to its own conclusion, so a close attempted on a complaint in `INSPECTION_SCHEDULED`, `INSPECTED` or `ABATEMENT_ORDERED`, or on one already closed, is rejected with `ERR_INVALID_STATE`. From `RECEIVED` either accepted reason may be used, giving the legs `RECEIVED → CLOSED_WITHDRAWN` and `RECEIVED → CLOSED_DUPLICATE`. From `TRIAGED` only `WITHDRAWN` is available, giving the leg `TRIAGED → CLOSED_WITHDRAWN`; de-duplication belongs to the intake stage, so a `DUPLICATE` closure of a complaint that has already been triaged is likewise `ERR_INVALID_STATE`. Whichever leg fires, the chosen `closure_reason` is stamped along with `closed_at` at the current logical clock, the zone's `open_complaint_count` drops by one, and the zone's `rodent_index` and `posture` are recomputed.

One referential guard sits in front of every administrative closure: the parcel must be clear of live enforcement. If any abatement order on the same parcel is still in a non-terminal status — that is, in `ISSUED`, `SERVED`, `REINSPECTION_SCHEDULED`, `ESCALATED` or `CITY_ABATED` — the closure is refused with `ERR_OPEN_ORDER_EXISTS`. Only orders that have reached `COMPLIED` or `CLOSED` are considered settled.

Complaints can be listed with optional filters on `property_id`, on `zone_id` and on `status`, and read individually.

### 3.3. Booking and Running a Field Visit

Scheduling is a `Supervisor` responsibility, and one scheduling operation serves both kinds of visit. The payload declares the `kind` — `INITIAL` or `REINSPECTION` — names the `officer_id` who will make the visit, and books the window with `scheduled_start` and `scheduled_end`. An `INITIAL` visit additionally names the `complaint_id` it answers; a `REINSPECTION` instead names the `abatement_order_id` it verifies. Whichever parent is named, the new visit is created in status `SCHEDULED` with `property_id` copied from that parent, with `result`, `notes`, `started_at` and `completed_at` all null, and the assigned officer's `active_assignment_count` rises by one.

The booked window must be structurally sound before anything else about it is considered: `scheduled_end` must be strictly after `scheduled_start`, and the duration between them must be at least 30 minutes and at most 240 minutes, both bounds inclusive. A window that inverts, collapses to zero, runs shorter than half an hour or longer than four hours is rejected with `ERR_VALIDATION`.

An `INITIAL` visit may only be booked against a complaint currently in `TRIAGED`; any other complaint status yields `ERR_COMPLAINT_NOT_TRIAGED`. Booking one moves the complaint `TRIAGED → INSPECTION_SCHEDULED`. A `REINSPECTION` may only be booked against an order currently in `SERVED`; any other order status yields `ERR_ORDER_NOT_SERVED`, and booking one moves the order `SERVED → REINSPECTION_SCHEDULED`. Two further rules bind re-inspections specifically. The assigned `officer_id` must differ from the officer who ran the order's originating inspection — otherwise `ERR_REINSPECTION_SAME_OFFICER` — and the visit may not be booked to begin before the owner's window has run out: if `scheduled_start` is strictly earlier than the order's `compliance_deadline`, the booking is refused with `ERR_REINSPECTION_TOO_EARLY`. A `scheduled_start` falling exactly on the deadline is acceptable.

Two collision rules protect the calendar, and they are deliberately asymmetric. **Officer availability** is evaluated against every other inspection of the same officer that is currently `SCHEDULED` or `IN_PROGRESS`, using closed comparison on both ends plus a 30-minute travel buffer: the two bookings collide when the new visit's `scheduled_start` is at or before the other visit's `scheduled_end` extended by 30 minutes, *and* the other visit's `scheduled_start` is at or before the new visit's `scheduled_end` extended by 30 minutes. Because the comparison is closed, two windows that are exactly back-to-back — and indeed two windows separated by exactly the travel buffer — do collide, and the booking is rejected with `ERR_OFFICER_SCHEDULE_CONFLICT`. **Site availability** is evaluated against every other `SCHEDULED` or `IN_PROGRESS` inspection on the same parcel, with no buffer and half-open comparison: the two overlap when the new visit's `scheduled_start` is strictly before the other's `scheduled_end` *and* the other's `scheduled_start` is strictly before the new visit's `scheduled_end`. Two windows that merely touch at an endpoint therefore do not overlap and are allowed; a genuine overlap yields `ERR_PROPERTY_INSPECTION_OVERLAP`. When both rules could fire, the officer rule is evaluated first.

Inspections can be listed with optional filters on `complaint_id`, on `abatement_order_id`, on `property_id`, on `officer_id`, on `status` and on `kind`, or read one at a time.

**Starting the visit.** The assigned officer, acting as `Inspector`, starts the visit; only they may do so, since `X-User-ID` must equal the visit's `officer_id`. The visit must be in `SCHEDULED` — a second start attempt, or a start on a completed visit, is `ERR_INVALID_STATE` — and the officer's `certification_expires_at` must be strictly later than the current logical clock, failing which the start is refused with `ERR_CERTIFICATION_EXPIRED`. A successful start stamps `started_at` with the current logical clock and moves the visit `SCHEDULED → IN_PROGRESS`.

### 3.4. Harborage, Attractants and the Chronic-Offender Score

While a visit is `IN_PROGRESS`, its assigned officer records exactly one assessment of what they found. The assessment captures three observation scores, each an integer from 0 to 10 inclusive — `harborage_score` for shelter and nesting opportunity, `attractant_score` for available food and water, and `sanitation_score` for sanitation deficiencies — together with a `burrow_count` of active burrows counted on the parcel, which must be zero or more. Two optional fields accompany them: `evidence_photo_count`, the number of photographs attached, defaulting to 0 and never negative, and `recommended_actions`, an array of abatement actions the inspector recommends, defaulting to an empty array. The assessment row carries the `inspection_id` of the visit it was taken during, and, like every observation record in this system, it has an `id` and a `created_at` but neither an `updated_at` nor a `version`.

At most one assessment may exist per visit. A second attempt is refused with `ERR_ASSESSMENT_ALREADY_EXISTS`, and an attempt to record one against a visit that is not `IN_PROGRESS` is `ERR_INVALID_STATE`. The assessments of a visit can be listed, returning zero or one row.

**The infestation index.** Each assessment yields a composite `infestation_index` between 0.00 and 100.00. The three observation scores are combined with fixed weights — harborage counts for 0.40, attractants for 0.35 and sanitation for 0.25 — and that weighted sum is multiplied by 10 to lift the 0–10 observation range onto a 0–100 scale. A burrow surcharge is then computed as 3.0 points for each active burrow counted, capped so that it never contributes more than 15.0 points however many burrows were found. The scaled weighted sum and the surcharge are added, the result is capped at 100.0, and the capped value is rounded half-up to two decimal places. Only this one assessment's four input values participate; no other assessment on the parcel influences it.

From the index follows the `infestation_tier`: `SEVERE` when the index is at least 65.00, otherwise `MODERATE` when it is at least 35.00, otherwise `LOW`. That tier is what later drives the owner's compliance window and the city's standard cost estimate.

**Two chronic scores, deliberately different.** A parcel carries two related numbers that must never be conflated. The moment an assessment is created, the parcel's `provisional_chronic_score` is overwritten with that single assessment's `infestation_index`, verbatim: no time decay, no repeat-offence surcharge, no history. The provisional figure is a single-observation working view for the officer in the field; it gates nothing, and it never sets `chronic_flag`.

The parcel's authoritative `chronic_score` is written only when an `INITIAL` visit completes with the result `VIOLATION_FOUND`, and it is a decayed weighted mean over the parcel's confirmed violation history. The qualifying set is every assessment on that parcel whose parent visit has reached `COMPLETED` with result `VIOLATION_FOUND` and whose parent visit's `completed_at` lies within 365 days of the current logical clock, inclusive at both ends — meaning an age of exactly 0 days and an age of exactly 365 days both qualify. Assessments taken on visits that ended `NO_VIOLATION` or `NO_ACCESS`, and assessments taken on re-inspection visits, are excluded outright. The qualifying assessments are ordered by their parent visit's `completed_at` ascending, and ties are broken by the assessment's own `created_at` ascending.

Each qualifying assessment is weighted by its age. Its age in whole days is the elapsed time from its parent visit's `completed_at` to the current logical clock, truncated downwards to a whole number of days. That day count is then divided by 30 and truncated downwards to a whole number of completed 30-day blocks, and the weight is 1.0 less 0.10 for each such block, floored at 0.0 so that no assessment ever contributes negatively. An assessment aged 0 to 29 days therefore weighs 1.00, one aged 30 to 59 days weighs 0.90, one aged 300 to 329 days weighs 0.00 and contributes nothing. The weighted mean is the sum of each assessment's `infestation_index` multiplied by its weight, divided by the sum of the weights; the divisor is never zero because the assessment from the visit just completed always carries a weight of 1.0.

A repeat-offence surcharge of 8.0 points is then added for every qualifying assessment beyond the first — with three qualifying assessments the surcharge is 16.0, and with one it is 0.0. The sum of the weighted mean and the surcharge is capped at 100.0 and rounded half-up to two decimal places to give `chronic_score`. Finally, `chronic_flag` becomes true when `chronic_score` is at least 60.00 and false otherwise. Only this reviewed computation may move `chronic_flag`; the provisional figure may not. Because the two computations see different inputs, the same underlying assessment routinely leaves `provisional_chronic_score` and `chronic_score` holding different numbers on the same parcel, and both remain observable.

### 3.5. Completing the Visit and the Cascade It Sets Off

Closing out a visit is the single most consequential operation in the system. The assigned officer supplies the `result` and optional `notes`; the visit must be `IN_PROGRESS`, else `ERR_INVALID_STATE`, and `X-User-ID` must equal the visit's `officer_id`.

The permitted results depend on the visit's `kind`. An `INITIAL` visit may end `VIOLATION_FOUND`, `NO_VIOLATION` or `NO_ACCESS`. A `REINSPECTION` may end `COMPLIANT`, `NON_COMPLIANT` or `NO_ACCESS`. Any other pairing — `VIOLATION_FOUND` or `NO_VIOLATION` reported on a re-inspection, `COMPLIANT` or `NON_COMPLIANT` reported on an initial visit — is rejected with `ERR_RESULT_KIND_MISMATCH`. A completion claiming `VIOLATION_FOUND` additionally requires that exactly one assessment already exists for the visit; without one, the completion is refused with `ERR_ASSESSMENT_REQUIRED`.

Whichever result is recorded, four things always happen: `completed_at` is stamped from the logical clock and the `result` stored, the visit moves `IN_PROGRESS → COMPLETED`, the officer's `active_assignment_count` falls by one, and the parcel's `last_inspection_at` is set to that `completed_at`.

Beyond those, the result selects a branch, and each branch is specified in full:

- **`INITIAL` ending `VIOLATION_FOUND`** starts a four-hop cascade. The linked complaint moves `INSPECTION_SCHEDULED → INSPECTED`, recording the confirmed violation. That transition in turn triggers the reviewed chronic recomputation of §3.4: the parcel's `chronic_score` is rewritten, `chronic_flag` is set according to whether that score reached 60.00, and the parcel's `version` is incremented by one. If and only if `chronic_flag` flipped from false to true on that recomputation, a fourth hop fires: the zone's `chronic_property_count` rises by one, the zone's `rodent_index` and `posture` are recomputed, and the zone's `version` is incremented by one. When the flag was already true, or remains false, the fourth hop does not fire.
- **`INITIAL` ending `NO_VIOLATION`** closes the case: the linked complaint moves `INSPECTION_SCHEDULED → CLOSED_NO_VIOLATION` with `closure_reason` `NO_VIOLATION` and `closed_at` stamped, the zone's `open_complaint_count` falls by one, and the zone's `rodent_index` and `posture` are recomputed. The parcel's `chronic_score` is explicitly *not* recomputed, because no violation was confirmed.
- **`INITIAL` ending `NO_ACCESS`** returns the case to the queue: the linked complaint moves `INSPECTION_SCHEDULED → TRIAGED` so that a further visit can be booked against it. The zone's `open_complaint_count` is unchanged, because the case is still open. This is the leg that makes the complaint lifecycle cyclic — a parcel whose gate is locked can be scheduled, attempted and re-scheduled indefinitely.
- **`REINSPECTION` ending `COMPLIANT`** moves the linked order `REINSPECTION_SCHEDULED → COMPLIED` and stamps the order's `closed_at`; the parcel's `open_order_count` falls by one and the parcel's `version` is incremented by one; the complaint that originated the order moves `ABATEMENT_ORDERED → CLOSED_RESOLVED` with `closure_reason` `RESOLVED` and `closed_at` stamped; the zone's `open_complaint_count` falls by one and the zone's `rodent_index` and `posture` are recomputed. An order that reaches `COMPLIED` may never be billed: no cost-recovery invoice can be prepared against it.
- **`REINSPECTION` ending `NON_COMPLIANT`** moves the linked order `REINSPECTION_SCHEDULED → ESCALATED`, raises the order's `escalation_level` by one but never above the ceiling of 2 — a third failed re-inspection leaves it saturated at 2 — and increments the order's `version` by one.
- **`REINSPECTION` ending `NO_ACCESS`** moves the linked order `REINSPECTION_SCHEDULED → SERVED` with its `compliance_deadline` left exactly as it was, so a further re-inspection can be booked without the owner gaining or losing time.

### 3.6. The Abatement Order, Its Notices and the Negotiation Loop

An abatement order is the program's formal demand that an owner fix what an officer documented. A `Supervisor` issues one by naming the `inspection_id` of the visit that documented the violation, listing the corrective actions in `required_actions` — an array that must contain at least one element, an empty array being `ERR_VALIDATION` — and quoting `expected_property_version` as described in §2.6. The originating visit must have reached `COMPLETED`, else `ERR_INSPECTION_NOT_COMPLETED`, and its `result` must be `VIOLATION_FOUND`, else `ERR_NO_VIOLATION_FOUND` (HTTP 422). The issuing supervisor may not be the officer who ran that visit, else `ERR_SEGREGATION_OF_DUTIES`.

The new order is created in status `ISSUED` with `escalation_level` 0, `extension_count` 0, `extension_days_total` 0, `education_advisory_served` false, and `compliance_deadline`, `served_at`, `actual_labor_hours`, `actual_materials_cents`, `abated_at` and `closed_at` all null. Its `property_id` is copied from the originating visit, its `issued_by_officer_id` is taken from the issuer's `X-User-ID`, and its `infestation_tier_at_issue` is copied from the assessment recorded during that visit — a snapshot that is never re-derived even if the parcel's condition later changes. Issuance also moves the linked complaint `INSPECTED → ABATEMENT_ORDERED`, raises the parcel's `open_order_count` by one and increments the parcel's `version` by one. Orders can be read individually and listed with optional filters on `property_id`, on `inspection_id`, on `issued_by_officer_id` and on `status`.

**Serving the owner.** An order has no legal effect until the owner is served, and service is a two-step affair: a notice is generated, then a process server's outcome is recorded against it. An `IntakeClerk` or a `Supervisor` generates a notice on an order, declaring its `notice_type` — `ABATEMENT_ORDER` for the statutory demand, `EDUCATIONAL_ADVISORY` for the prevention packet, `FINAL_WARNING` for the last chance before the city acts, or `LIEN_INTENT` for the pre-lien warning — and the `delivery_method` used to serve it: `FIRST_CLASS_MAIL`, `CERTIFIED_MAIL`, `PERSONAL_SERVICE` or `POSTING`. The notice is created in status `PENDING_SERVICE`, its `sent_at` stamped from the logical clock, its `served_at` and `service_outcome` null, and its `recipient_address` copied from the owner's `mailing_address` as it stands at that moment — later edits to the owner's address of record do not rewrite an already-generated notice. Notices carry an `abatement_order_id` identifying the order they announce, and the notices of an order can be listed.

Notice sequencing is regulated. The very first notice generated on an order must be an `ABATEMENT_ORDER` notice; and a `FINAL_WARNING` may only be generated while the order is in `ESCALATED`. Either violation is refused with `ERR_NOTICE_SEQUENCE_INVALID` (HTTP 422).

**Recording service.** An `IntakeClerk` records the process server's `service_outcome`, which is `DELIVERED`, `REFUSED` or `UNDELIVERABLE`. The notice must still be in `PENDING_SERVICE`; recording a second outcome on a notice that already reached `SERVED` or `UNDELIVERABLE` is refused with `ERR_NOTICE_ALREADY_SERVED`. Under the program ordinance a refusal is deemed good service, so `DELIVERED` and `REFUSED` both move the notice `PENDING_SERVICE → SERVED` and stamp its `served_at` with the current logical clock. An `UNDELIVERABLE` outcome moves the notice `PENDING_SERVICE → UNDELIVERABLE`, leaves `served_at` null and leaves the order untouched — a further notice must be generated to advance the order.

Good service then acts on the order according to the notice's type. An `ABATEMENT_ORDER` notice served while the order is `ISSUED` moves the order `ISSUED → SERVED`, copies the notice's `served_at` onto the order's `served_at`, derives the `compliance_deadline` as described below, and increments the order's `version` by one. A `FINAL_WARNING` notice served while the order is `ESCALATED` moves the order `ESCALATED → SERVED`, again stamping `served_at`, recomputing a deadline that is necessarily shorter because the escalation level is now at least 1, and incrementing the order's `version` by one; crucially, neither `extension_count` nor `extension_days_total` is reset by this leg, so an owner who already consumed their extension does not get another. An `EDUCATIONAL_ADVISORY` notice served on the order sets `education_advisory_served` to true and increments the order's `version` by one, without changing the order's status — that flag is the sole gate on the education credit in §3.7. A `LIEN_INTENT` notice served on the order changes no order state at all.

**The compliance window.** Whenever service moves an order into `SERVED`, the deadline is derived fresh. The window starts at 14 days. If the order's `infestation_tier_at_issue` is `SEVERE`, the window is reduced to 7 days if that is shorter than what has been derived so far. If the containing zone's `posture` is `HOTSPOT` at the moment of service, the window is reduced to 5 days if that is shorter than what has been derived so far. If the order's `escalation_level` is 1 or more, the window is reduced to 7 days if that is shorter than what has been derived so far. Each of those three adjustments only ever shortens the window, so the shortest applicable value wins: a `SEVERE` order served in a `HOTSPOT` zone receives 5 days, not 7 and not 12. The `compliance_deadline` is then the notice's `served_at` plus that number of days, preserving the exact time of day of `served_at`. Any extension days already granted on the order are added on top of the derived window.

**Granting time.** A `Supervisor` may grant the owner one extension, supplying `extension_days` and a written `reason`. The order must be in `SERVED` or `ESCALATED`; anywhere else is `ERR_INVALID_STATE`. At most one extension exists per order: once `extension_count` has reached 1, a further request is refused with `ERR_EXTENSION_LIMIT_REACHED` (422), and that check is made before the requested length is examined. The length must be a whole number of days between 1 and 14 inclusive; anything below 1 or above 14 is refused with `ERR_EXTENSION_WINDOW_EXCEEDED`. A granted extension pushes `compliance_deadline` later by the granted number of days, raises `extension_count` by one, adds the granted days to `extension_days_total`, and increments the order's `version` by one.

**The negotiation loop.** Together these rules form a cycle that an obstinate parcel can traverse repeatedly: an order is `SERVED`, a re-inspection is booked and the order becomes `REINSPECTION_SCHEDULED`, the re-inspection finds the work undone and the order becomes `ESCALATED`, a `FINAL_WARNING` is served and the order returns to `SERVED` with a shorter window. Each pass through `ESCALATED` raises `escalation_level`, which saturates at 2.

**City abatement.** When the owner will not act, the city does the work itself and a `Supervisor` records what it cost, supplying `actual_labor_hours` — a positive number carried to at most two decimal places — `actual_materials_cents` as a whole number of cents of zero or more, and optionally some `crew_notes`. There are two ways in. From `ESCALATED` the recording is allowed at any time. From `SERVED` it is allowed only once the owner's window has run out: if the current logical clock is strictly before the order's `compliance_deadline`, the recording is refused with `ERR_DEADLINE_NOT_PASSED`, while a clock exactly at the deadline is permitted. From any other status the attempt is `ERR_INVALID_STATE`. Either way the order moves to `CITY_ABATED`, `abated_at` is stamped from the logical clock, the two actuals are stored, and the order's `version` is incremented by one.

The `SERVED → CITY_ABATED` fork matters to the bill. It skips the re-inspection loop entirely, so the order arrives at cost recovery with `escalation_level` still 0, which means the penalty multiplier is 1.00 and no penalty line is billed at all. The `ESCALATED → CITY_ABATED` route, by contrast, always arrives with `escalation_level` at 1 or 2 and therefore always carries a penalty.

### 3.7. Recovering the Cost

Once the city has done the work, a `FinanceOfficer` prepares the bill. Preparation names the `abatement_order_id` being recovered and quotes `expected_abatement_order_version`. The order must be in `CITY_ABATED`, else `ERR_ORDER_NOT_ABATED`; in particular an order that reached `COMPLIED` because the owner did the work can never be billed. Only one live invoice may exist per order: if a non-`VOID` invoice already exists for that order, preparation is refused with `ERR_INVOICE_ALREADY_EXISTS`. Voided invoices do not block a replacement, which is exactly how a mis-prepared bill is corrected.

The invoice is created with `billing_status` `DRAFT` and `lien_status` `NONE`. Its `prepared_by_user_id` is the preparer's `X-User-ID`, its `property_id` is copied from the order and its `owner_id` from that parcel. `approved_by_user_id`, `final_total_cents`, `labor_line_cents`, `materials_line_cents`, `penalty_line_cents`, `education_credit_cents`, `admin_fee_cents`, `hardship_discount_cents`, `due_at`, `paid_at`, `lien_filed_at`, `voided_at` and `void_reason` all begin null, while `amount_paid_cents` and `balance_due_cents` begin 0. The `estimated_total_cents` is written immediately by the estimate run of the costing rule. Preparation also increments the order's `version` by one — which is why a client that prepares an invoice, sees it voided, and prepares a replacement must re-read the order's version in between. Invoices can be read individually and listed with optional filters on `abatement_order_id`, on `property_id`, on `owner_id`, on `billing_status` and on `lien_status`.

**The costing rule, and its two runs.** The same eleven-step computation is run twice against the same order, and the two runs differ only in the two figures they feed in at the top. The **estimate** run, performed at preparation and stored in `estimated_total_cents`, uses the tier-standard allowances keyed on the order's `infestation_tier_at_issue`: 2 labour hours and 5000 cents of materials for `LOW`, 4 hours and 12000 cents for `MODERATE`, 8 hours and 25000 cents for `SEVERE`. It is what the owner sees on the pre-bill. The **final** run, performed at approval and stored in `final_total_cents` together with the six line fields, uses the crew's recorded `actual_labor_hours` and `actual_materials_cents` instead. The estimate is never overwritten by the final run, so both numbers stay observable on the same row and will ordinarily differ.

The eleven steps run in this exact order, and no step may be reordered:

1. The **labour line** is the number of labour hours in play multiplied by the crew rate of 8525 cents per hour, rounded half-up to a whole number of cents, and stored as `labor_line_cents`.
2. The **materials line** is the material figure in play, taken as whole cents with no adjustment, and stored as `materials_line_cents`.
3. The **subtotal** is the labour line plus the materials line.
4. The **penalty line** is the subtotal multiplied by the order's penalty multiplier less 1.00, rounded half-up to whole cents, and stored as `penalty_line_cents`. The multiplier is 1.00 at `escalation_level` 0, 1.25 at level 1 and 1.50 at level 2 — so an unescalated order produces a penalty line of exactly 0, a once-escalated order a quarter of its subtotal, and a twice-escalated order a half.
5. The **education credit** is the subtotal multiplied by 0.10, rounded half-up to whole cents, when the order's `education_advisory_served` is true; when it is false the credit is exactly 0. It is stored as `education_credit_cents`.
6. The **fee base** is the subtotal plus the penalty line minus the education credit.
7. The **administrative fee** is the fee base multiplied by 0.15, rounded half-up to whole cents, and stored as `admin_fee_cents`.
8. The **pre-discount total** is the fee base plus the administrative fee.
9. The **hardship rate** is chosen next. When the owner's `hardship_certified` is true and the pre-discount total is at least 100000 cents, the rate is 0.10; when the owner's `hardship_certified` is true and the pre-discount total is at least 50000 cents but below 100000, the rate is 0.05; in every other case — including every case where `hardship_certified` is false — the rate is 0.00.
10. The **hardship discount** is the *subtotal from step 3* multiplied by that rate, rounded half-up to whole cents, and stored as `hardship_discount_cents`.
11. The **total** is the pre-discount total minus the hardship discount.

Two properties of that sequence are easy to get wrong and are therefore stated explicitly. Every line produced in steps 1, 4, 5, 7 and 10 is rounded to whole cents *before* it enters any later step; carrying unrounded products forward and rounding once at the end produces a different number of cents and is wrong. And the hardship tier is selected on the **pre-discount total of step 8**, which already includes the administrative fee, while the discount itself is applied to the **subtotal of step 3**; the administrative fee is never recomputed after the discount is taken. Selecting the tier on the subtotal instead changes the result.

**Approval.** A `ProgramAdmin` approves the invoice, optionally sending `escalated_approval` as true. The invoice must be in `DRAFT`, else `ERR_INVALID_STATE`, and the approver's `X-User-ID` must differ from `prepared_by_user_id`, else `ERR_SELF_APPROVAL_FORBIDDEN`. The final run of the costing rule is then evaluated: if the resulting `final_total_cents` exceeds 500000 cents and `escalated_approval` was not sent as true, the approval is refused with `ERR_APPROVAL_LIMIT_EXCEEDED`; a total exactly equal to 500000 needs no escalation. On success `billing_status` moves `DRAFT → APPROVED`, `approved_by_user_id` is set from `X-User-ID`, `final_total_cents` and the six line fields are written, `balance_due_cents` is set equal to `final_total_cents`, `due_at` is set to the current logical clock plus 30 days, and the owner's `outstanding_balance_cents` is recomputed to include the newly approved balance.

**Payments.** A `FinanceOfficer`, or the `PropertyOwner` whose invoice it is, posts a payment carrying `amount_cents` — a positive integer, a zero or negative amount being `ERR_VALIDATION` — and a `method` of `CHECK`, `ACH`, `CARD` or `CASH`. Payments are only accepted while `billing_status` is `APPROVED` or `PARTIALLY_PAID`; a `DRAFT`, `PAID` or `VOID` invoice rejects them with `ERR_INVOICE_NOT_APPROVED`. An amount greater than `balance_due_cents` is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`.

A payment strictly smaller than the outstanding balance adds its amount to `amount_paid_cents`, subtracts it from `balance_due_cents`, reduces the owner's `outstanding_balance_cents` by the same amount and raises the owner's `lifetime_paid_cents` by it. From `APPROVED` this moves `billing_status` to `PARTIALLY_PAID`; from `PARTIALLY_PAID` the invoice simply remains `PARTIALLY_PAID`, and any number of such payments may be posted.

A payment exactly equal to the outstanding balance settles the invoice and opens a four-hop cascade. First, `amount_paid_cents` rises by the amount, `balance_due_cents` becomes 0, `paid_at` is stamped from the logical clock, `billing_status` becomes `PAID` — reached from either `APPROVED` or `PARTIALLY_PAID` — the owner's `outstanding_balance_cents` is reduced by the cleared amount and their `lifetime_paid_cents` raised by it, and if the invoice's `lien_status` was `FILED` it moves to `RELEASED` with the parcel's `lien_encumbered` recomputed. Second, the linked abatement order moves `CITY_ABATED → CLOSED`, stamping the order's `closed_at`, dropping the parcel's `open_order_count` by one and incrementing the parcel's `version` by one. Third, the complaint that originated the order moves `ABATEMENT_ORDERED → CLOSED_RESOLVED` with `closure_reason` `RESOLVED` and `closed_at` stamped. Fourth, the zone's `open_complaint_count` falls by one and its `rodent_index` and `posture` are recomputed.

**Liens.** A `FinanceOfficer` files a lien on the parcel for an unpaid, past-due invoice; the operation takes no payload. The invoice's `lien_status` must be `NONE` — a second lien on the same invoice is `ERR_INVALID_STATE` — and its `billing_status` must be `APPROVED` or `PARTIALLY_PAID`, else `ERR_INVOICE_NOT_APPROVED`. Two thresholds must both be met: `balance_due_cents` must be at least 25000 cents, and the current logical clock must be at or past `due_at` plus 60 days. A balance below 25000, or a clock strictly earlier than that 60-day mark, is refused with `ERR_LIEN_THRESHOLD_NOT_MET`. Filing moves `lien_status` `NONE → FILED`, stamps `lien_filed_at`, sets the parcel's `lien_encumbered` to true and increments the parcel's `version` by one. The lien axis evolves independently of the billing axis: an invoice may be `APPROVED` with a lien `FILED`, or `PARTIALLY_PAID` with a lien `FILED`, and `lien_status` moves `FILED → RELEASED` exactly when the billing axis reaches `PAID` or `VOID`. On release, the parcel's `lien_encumbered` is set back to false only if no other invoice on that parcel still holds a `FILED` lien.

**Voiding, and the balance it must restore.** Voiding is the compensating action for approval, and a `FinanceOfficer` performs it with a written `void_reason`. An invoice already in `PAID` or `VOID` cannot be voided; the attempt is `ERR_INVALID_STATE`. Voiding always stamps `voided_at` from the logical clock and sets `balance_due_cents` to 0, and the accounting consequence depends on where the invoice was.

From `DRAFT`, the owner's `outstanding_balance_cents` is unchanged, because a draft invoice never entered that balance in the first place. From `APPROVED`, the owner's `outstanding_balance_cents` is reduced by exactly the `balance_due_cents` that is being cancelled, which restores the owner's balance to precisely the figure it held before the approval — the invariant the void exists to guarantee — and if the `lien_status` was `FILED` it moves to `RELEASED` with the parcel's `lien_encumbered` recomputed. From `PARTIALLY_PAID`, the owner's `outstanding_balance_cents` is likewise reduced by the cancelled `balance_due_cents`, while `amount_paid_cents` is retained on the invoice: money already collected is not unwound, and the owner's `lifetime_paid_cents` is unaffected by the void. In every case the linked abatement order stays in `CITY_ABATED`, deliberately, so that a corrected replacement invoice can be prepared against it.

**The owner's two aggregates.** Both figures on an owner record are recomputed from scratch after every approval, payment and void rather than being adjusted in place. `outstanding_balance_cents` is the sum of `balance_due_cents` across that owner's invoices whose `billing_status` is `APPROVED` or `PARTIALLY_PAID`; invoices in `DRAFT`, `PAID` or `VOID` contribute nothing. `lifetime_paid_cents` is the sum of `amount_paid_cents` across that owner's invoices whose `billing_status` is `APPROVED`, `PARTIALLY_PAID` or `PAID`.

### 3.8. Bait Stations, Surveillance and the Zone Posture

An `Inspector` installs a bait station on a parcel, naming the `property_id` it sits on, a `station_code` label that must be unique within that parcel (a repeat within the same parcel is `ERR_DUPLICATE_CODE`, though two different parcels may each use the same label), and a `bait_type` of `ANTICOAGULANT`, `SNAP_TRAP`, `GLUE_BOARD` or `BAIT_BLOCK`. The station is created in status `ACTIVE`, its `zone_id` copied from the parcel and its `installed_at` stamped from the logical clock, with `last_reading_at` null, `reading_count` 0 and `cumulative_take_pct` 0. Installation raises the zone's `active_station_count` by one. Stations can be read individually and listed with optional filters on `property_id`, on `zone_id` and on `status`.

Servicing visits are recorded as surveillance readings against a station. The technician reports `take_pct`, an integer from 0 to 100 inclusive describing the percentage of bait consumed since the previous servicing; `activity_sign_count`, a count of zero or more droppings, runways, gnaw marks and other activity signs observed; `station_condition`, the physical state of the device, one of `INTACT`, `DAMAGED` or `MISSING`; and optionally `rebaited`, a flag that is true when the technician replenished bait during the visit and which defaults to true. Each reading carries the `bait_station_id` of the station it services and a `reading_at` stamped from the logical clock, and — being an observation record — it has an `id` and a `created_at` but no `updated_at` and no `version`. Readings on a station can be listed.

Two guards protect the reading stream. A station whose status is already `REMOVED` accepts no further readings and rejects them with `ERR_STATION_DECOMMISSIONED`. And a station may not be serviced again within 24 hours of its `last_reading_at`: a reading recorded strictly less than 24 hours after the previous one is refused with `ERR_READING_TOO_SOON`, while one recorded exactly 24 hours later is accepted. A station with no prior reading is never too soon.

An accepted reading updates the station's `last_reading_at` to this reading's `reading_at`, raises `reading_count` by one, and adds this reading's `take_pct` to the running `cumulative_take_pct`. The reported `station_condition` then drives the station's own lifecycle. A condition of `DAMAGED` moves an `ACTIVE` station to `DAMAGED`; a condition of `INTACT` moves a `DAMAGED` station back to `ACTIVE`, which is the repair loop that makes the station lifecycle cyclic; a condition of `MISSING` moves a station to `REMOVED` from either `ACTIVE` or `DAMAGED`. A condition that matches the station's present state leaves it where it is.

`ACTIVE` and `DAMAGED` are both treated as eligible for surveillance purposes, so the repair loop does not disturb the zone's `active_station_count` in either direction. Reaching `REMOVED` is different: it drops the zone's `active_station_count` by one and, more consequentially, removes *all* of that station's historical readings from the surveillance input set, after which the zone's `rodent_index` and `posture` are recomputed. `REMOVED` is terminal — a decommissioned station is never revived.

**The composite rodent index.** A zone's `rodent_index` is a weighted blend of three components measured over a closed 30-day window that ends at the current logical clock and begins exactly 30 days earlier; a reading or complaint sitting exactly on either boundary is inside the window.

The eligible stations of a zone are those whose `zone_id` matches and whose status is `ACTIVE` or `DAMAGED`. The window readings are the readings of those eligible stations whose `reading_at` falls inside the window. When there are no window readings at all, the bait component and the sign component are both exactly 0.00. Otherwise the **bait component** is the sum of `take_pct` across the window readings divided by the number of window readings, rounded half-up to two decimal places; and the **sign component** is the sum of `activity_sign_count` across the window readings divided by the number of window readings, multiplied by a scale factor of 12.5, capped at 100.0, and rounded half-up to two decimal places.

The **complaint component** counts the zone's complaints that are simultaneously open — status `RECEIVED`, `TRIAGED`, `INSPECTION_SCHEDULED`, `INSPECTED` or `ABATEMENT_ORDERED` — and were created inside the same closed 30-day window. That count is multiplied by 20.0, capped at 100.0, and rounded half-up to two decimal places.

The three rounded components are then blended: the bait component weighted 0.50, the sign component weighted 0.30 and the complaint component weighted 0.20, and the weighted sum is rounded half-up to two decimal places once more. The rounding order is deliberate — each component is rounded before the blend, and the blend is rounded again.

The `posture` follows directly from the resulting index: `HOTSPOT` when the index is at least 70.00, otherwise `ELEVATED` when the index is at least 40.00, otherwise `NORMAL`. Every path between the three postures is reachable in either direction as the index moves — `NORMAL → ELEVATED` and `ELEVATED → HOTSPOT` as it climbs, `NORMAL → HOTSPOT` when a single recompute jumps straight past the middle band, and `HOTSPOT → ELEVATED`, `ELEVATED → NORMAL` and `HOTSPOT → NORMAL` as it falls. Every recompute refreshes the zone's `last_index_recomputed_at` to the current logical clock, and a recompute that changes `posture` increments the zone's `version` by one.

Recomputation is triggered whenever a reading is recorded, whenever a bait station's status changes, whenever a complaint enters or leaves an open status — that is, at intake and at every closure or reopening — and on every read of the zone's surveillance summary. That summary is a computed read available to `ProgramAdmin`, `Supervisor` and `Inspector`: it recomputes the index against the current logical clock, refreshes the zone's stored `rodent_index`, `posture` and `last_index_recomputed_at` as a side effect, and returns `zone_id`, `rodent_index`, `posture`, the three components as `bait_component`, `sign_component` and `complaint_component`, the `in_window_reading_count` of readings that fed the first two components, the `eligible_station_count` of stations in `ACTIVE` or `DAMAGED`, the `open_complaint_count` of in-window open complaints that fed the third component, and the window boundaries as `window_start` and `window_end`.

**The zone's three counters** are a separate matter from the index and carry no time window at all. `open_complaint_count` is the number of complaints in the zone whose status is none of `CLOSED_NO_VIOLATION`, `CLOSED_RESOLVED`, `CLOSED_WITHDRAWN` or `CLOSED_DUPLICATE`. `chronic_property_count` is the number of parcels in the zone whose `chronic_flag` is true. `active_station_count` is the number of bait stations in the zone whose status is `ACTIVE` or `DAMAGED`. All three are recomputed from scratch — never patched incrementally — after complaint intake, after every complaint status change, after a parcel's `chronic_flag` flips, and after a bait station's status changes.

### 3.9. Program Reporting

`ProgramAdmin` and `Supervisor` users pull a program-wide roll-up, optionally narrowing it to a single zone by supplying `zone_id`. When the filter is supplied, complaints and parcels are scoped by their own `zone_id`, and orders and invoices are scoped through the zone of the parcel they concern; when it is omitted, the roll-up covers the whole program.

The roll-up reports twelve figures. `complaint_total` is the number of complaints in scope and `complaint_open` the number of those not in any of the four closed statuses, while `complaint_closed_resolved` counts those in `CLOSED_RESOLVED` specifically. `orders_issued` is the number of abatement orders in scope regardless of their current status, `orders_complied` the number now in `COMPLIED`, and `orders_city_abated` the number now in `CITY_ABATED`. `chronic_property_count` is the number of parcels in scope whose `chronic_flag` is true, and `hotspot_zone_count` the number of zones in scope whose `posture` is `HOTSPOT` — which is 1 or 0 when the report is narrowed to one zone. On the money side, `invoiced_cents` is the sum of `final_total_cents` over invoices that have been approved (that is, those whose `billing_status` is `APPROVED`, `PARTIALLY_PAID` or `PAID`), `collected_cents` is the sum of `amount_paid_cents` over all invoices in scope, `outstanding_cents` is the sum of `balance_due_cents` over invoices whose `billing_status` is `APPROVED` or `PARTIALLY_PAID`, and `liens_filed` is the number of invoices in scope whose `lien_status` is `FILED`.



## 4. Endpoint Definitions

Endpoints that bring a new record into existence — zones, owners, parcels, officers, complaints, inspections, assessments, abatement orders, notices, bait stations, surveillance readings and cost-recovery invoices — answer **201 Created** and return the new record. Every other successful call, including all state transitions, all payments, all reads, all list retrievals and the logical-clock move, answers **200 OK**. The table below is a routing summary only: the request payloads, the response side effects and the conditions under which each call fails are specified in §2 and §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| `POST` | `/vector-control/_clock/set_current_utc` | Test-driving endpoint: sets the server's logical clock | `ProgramAdmin` |
| `POST` | `/vector-control/zones` | Create a surveillance zone | `ProgramAdmin` |
| `GET` | `/vector-control/zones/{id}` | Read one zone including its derived posture and counters | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `FinanceOfficer` |
| `GET` | `/vector-control/zones/{id}/surveillance-summary` | Computed read: recomputes calculation zone_rodent_index for the zone against the current logical clock and returns every component of the composite index | `ProgramAdmin`, `Supervisor`, `Inspector` |
| `POST` | `/vector-control/property-owners` | Register a property owner of record | `ProgramAdmin` |
| `GET` | `/vector-control/property-owners/{id}` | Read one owner including the aggregated outstanding balance | `ProgramAdmin`, `Supervisor`, `FinanceOfficer`, `PropertyOwner` |
| `POST` | `/vector-control/properties` | Register a parcel inside a zone | `ProgramAdmin` |
| `GET` | `/vector-control/properties/{id}` | Read one parcel including its chronic scores, open_order_count, lien_encumbered flag and current version | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `FinanceOfficer`, `PropertyOwner` |
| `GET` | `/vector-control/properties` | List parcels, filterable by zone and by owner | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `FinanceOfficer` |
| `POST` | `/vector-control/officers` | Register a program officer; the returned id is the X-User-ID an Inspector or Supervisor presents | `ProgramAdmin` |
| `POST` | `/vector-control/complaints` | Intake a vector or rodent complaint against a parcel | `IntakeClerk`, `PropertyOwner` |
| `GET` | `/vector-control/complaints/{id}` | Read one complaint | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `PropertyOwner` |
| `GET` | `/vector-control/complaints` | List complaints, filterable by property, zone and status | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk` |
| `POST` | `/vector-control/complaints/{id}/triage` | Supervisor triage: confirm or override severity (one of ROUTINE, HIGH, CRITICAL) and re-derive dispatch priority and the response deadline | `Supervisor` |
| `POST` | `/vector-control/complaints/{id}/close` | Close a complaint administratively | `Supervisor` |
| `POST` | `/vector-control/inspections` | Schedule an inspection visit: an INITIAL visit against a triaged complaint, or a REINSPECTION against a served abatement order | `Supervisor` |
| `GET` | `/vector-control/inspections/{id}` | Read one inspection | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk` |
| `GET` | `/vector-control/inspections` | List inspections, filterable by complaint, abatement order, property, officer and status | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk` |
| `POST` | `/vector-control/inspections/{id}/start` | Assigned officer starts the visit; rejected when the officer's certification has expired | `Inspector` |
| `POST` | `/vector-control/inspections/{id}/assessments` | Record the harborage / attractant / sanitation assessment for an in-progress visit | `Inspector` |
| `GET` | `/vector-control/inspections/{id}/assessments` | List the assessments recorded during a visit (zero or one) | `ProgramAdmin`, `Supervisor`, `Inspector` |
| `POST` | `/vector-control/inspections/{id}/complete` | Close out the visit with its result; this is the entry point of the inspection completion cascade | `Inspector` |
| `POST` | `/vector-control/abatement-orders` | Issue an abatement order from a completed inspection that found a violation; the issuing Supervisor may not be the inspecting officer | `Supervisor` |
| `GET` | `/vector-control/abatement-orders/{id}` | Read one abatement order including its current version, deadline and escalation level | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `FinanceOfficer`, `PropertyOwner` |
| `GET` | `/vector-control/abatement-orders` | List abatement orders, filterable by property, originating inspection, issuing officer and status | `ProgramAdmin`, `Supervisor`, `Inspector`, `IntakeClerk`, `FinanceOfficer` |
| `POST` | `/vector-control/abatement-orders/{id}/notices` | Generate an owner notice for an order: the statutory ABATEMENT_ORDER notice, an EDUCATIONAL_ADVISORY packet, a FINAL_WARNING or a LIEN_INTENT notice | `IntakeClerk`, `Supervisor` |
| `GET` | `/vector-control/abatement-orders/{id}/notices` | List the notices generated for an order | `ProgramAdmin`, `Supervisor`, `IntakeClerk`, `FinanceOfficer`, `PropertyOwner` |
| `POST` | `/vector-control/notices/{id}/service-result` | Record the process server's outcome; DELIVERED and REFUSED both count as good service | `IntakeClerk` |
| `POST` | `/vector-control/abatement-orders/{id}/extend` | Grant the owner one deadline extension of 1 to 14 days | `Supervisor` |
| `POST` | `/vector-control/abatement-orders/{id}/city-abate` | Record that the city crew abated the nuisance itself, capturing the actual labor hours and materials that cost recovery will bill | `Supervisor` |
| `POST` | `/vector-control/bait-stations` | Install a bait station on a parcel | `Inspector` |
| `GET` | `/vector-control/bait-stations/{id}` | Read one bait station | `ProgramAdmin`, `Supervisor`, `Inspector` |
| `GET` | `/vector-control/bait-stations` | List bait stations, filterable by property, zone and status | `ProgramAdmin`, `Supervisor`, `Inspector` |
| `POST` | `/vector-control/bait-stations/{id}/readings` | Record a servicing visit on a station: bait take, activity signs and the station's physical condition | `Inspector` |
| `GET` | `/vector-control/bait-stations/{id}/readings` | List the surveillance readings recorded on a station | `ProgramAdmin`, `Supervisor`, `Inspector` |
| `POST` | `/vector-control/cost-recovery-invoices` | Prepare a cost-recovery invoice for a city-abated order; the ESTIMATE variant of the total is computed here | `FinanceOfficer` |
| `GET` | `/vector-control/cost-recovery-invoices/{id}` | Read one invoice including every computed line | `ProgramAdmin`, `Supervisor`, `FinanceOfficer`, `PropertyOwner` |
| `GET` | `/vector-control/cost-recovery-invoices` | List invoices, filterable by order, property, owner and status axes | `ProgramAdmin`, `Supervisor`, `FinanceOfficer` |
| `POST` | `/vector-control/cost-recovery-invoices/{id}/approve` | Approve and issue the invoice; the FINAL variant of the total is computed here and the approver may not be the preparer | `ProgramAdmin` |
| `POST` | `/vector-control/cost-recovery-invoices/{id}/payments` | Post a payment against an approved invoice; a payment that clears the balance starts the settlement cascade | `FinanceOfficer`, `PropertyOwner` |
| `POST` | `/vector-control/cost-recovery-invoices/{id}/lien` | File a lien on the parcel for an unpaid, past-due invoice | `FinanceOfficer` |
| `POST` | `/vector-control/cost-recovery-invoices/{id}/void` | Void an invoice; this is the compensating action for approval and must leave the owner's outstanding balance exactly as it was before approval | `FinanceOfficer` |
| `GET` | `/vector-control/reports/program-summary` | Program reporting roll-up across complaints, orders and cost recovery, optionally narrowed to one zone | `ProgramAdmin`, `Supervisor` |

## 5. Error Code Catalogue

Every failure response carries one of the identifiers below in `data.error_id`, together with the HTTP status shown. The conditions that trigger each identifier are stated where the corresponding rule is described in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_OFFICER_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_STALE_PROPERTY_VERSION` | 412 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STATION_DECOMMISSIONED` | 409 |
| `ERR_NOTICE_ALREADY_SERVED` | 409 |
| `ERR_COMPLAINT_NOT_TRIAGED` | 409 |
| `ERR_INSPECTION_NOT_COMPLETED` | 409 |
| `ERR_NO_VIOLATION_FOUND` | 422 |
| `ERR_ORDER_NOT_SERVED` | 409 |
| `ERR_ORDER_NOT_ABATED` | 409 |
| `ERR_INVOICE_NOT_APPROVED` | 409 |
| `ERR_CERTIFICATION_EXPIRED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_REINSPECTION_SAME_OFFICER` | 422 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 422 |
| `ERR_DUPLICATE_COMPLAINT` | 409 |
| `ERR_ASSESSMENT_ALREADY_EXISTS` | 409 |
| `ERR_ASSESSMENT_REQUIRED` | 422 |
| `ERR_RESULT_KIND_MISMATCH` | 422 |
| `ERR_NOTICE_SEQUENCE_INVALID` | 422 |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 |
| `ERR_EXTENSION_LIMIT_REACHED` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_OFFICER_SCHEDULE_CONFLICT` | 409 |
| `ERR_PROPERTY_INSPECTION_OVERLAP` | 409 |
| `ERR_REINSPECTION_TOO_EARLY` | 409 |
| `ERR_READING_TOO_SOON` | 409 |
| `ERR_EXTENSION_WINDOW_EXCEEDED` | 409 |
| `ERR_DEADLINE_NOT_PASSED` | 409 |
| `ERR_OPEN_ORDER_EXISTS` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_APPROVAL_LIMIT_EXCEEDED` | 422 |
| `ERR_LIEN_THRESHOLD_NOT_MET` | 422 |

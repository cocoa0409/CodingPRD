# Process Serving & Legal Support API — Product Requirements Document

## 1. Introduction

Law firms that need legal papers delivered to a named recipient face a deceptively intricate operational problem: a single summons or subpoena must move through licensed process servers, statutory diligence requirements that vary county by county, sworn affidavits, notarization, county e-filing, and finally a billing settlement — all while every step generates an auditable record. This API is the system of record for an agency that orchestrates that work end to end. It accepts a service request from a requesting firm, routes it to a process server who covers the relevant county, captures every field attempt with its date, time, and GPS coordinates, governs when and how service may be legally recorded, produces a notarized proof of service, files that proof with the county court, and reconciles the resulting charges against the firm's prepaid deposit.

The domain is unusually rule-dense. The legality of recording "substitute" or "posting" service, or of declaring a recipient unfindable, hinges on whether the server made enough distinct-day attempts to satisfy the county's statutory diligence floor. A server who personally hands papers to the recipient cannot also notarize their own sworn affidavit — that separation of duties is a hard requirement, not a courtesy. Rush jobs carry both a surcharge and a tight 48-hour clock. County e-filing windows have aggregate capacity limits. And because fees accrete from many independent billable events — base service, per-page printing, per-attempt labor, stakeouts, skip-traces, filings, and rush uplifts — the system must continuously reconcile a provisional quote against a final, frozen invoice.

This document specifies the complete contract: the resources and their fields, the state machines that govern each entity's lifecycle, the calculations that produce quotes and final fees, the validations that protect legal and fiscal integrity, the full endpoint surface, and the catalogue of error codes. Implementers should treat the business-logic narrative in Section 3 as authoritative for behavior, and the tables in Sections 4 and 5 as the structural index back into that narrative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `Admin`, `Dispatcher`, `Client`, `Server`, and `Notary`. If either header is missing, or if `X-User-Role` is not one of these five known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The same `ERR_UNAUTHORIZED` is returned when a role is permitted in general but the acting principal does not own the specific resource it is trying to mutate (an ownership mismatch).

The meaning of `X-User-ID` depends on the role, and ownership checks follow directly from it:

- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client. Ownership checks on any resource that references a Client compare the resource's `client_id` (directly, or transitively through its parent ServiceRequest) to `X-User-ID`. A Client may only act on and read its own service requests, documents, assignments, services, affidavits, filings, and invoice lines.
- When `X-User-Role` is `Server`, `X-User-ID` is the `id` of the acting Server. Ownership checks compare a resource's `server_id` (directly, or through the parent Assignment) to `X-User-ID`. A Server may accept or decline only its own offered assignments, log attempts only on its own assignment, record service or declare non-est only under its own assignment, schedule and transition only its own stakeouts, and sign only the affidavit on which it is the declarant.
- When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`.
- When `X-User-Role` is `Notary`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `notary_user_id` on the affidavit at the moment of notarization, but it is never matched against any entity's `id`; it is, however, compared against the affidavit's `declarant_server_id` to enforce separation of duties (described in Section 3).

`Admin` is the platform operator: it exclusively configures county jurisdictions, suspends or reactivates servers and clients, and sets the logical clock. `Dispatcher` runs the operational floor: it exclusively offers assignments to servers, pulls and reassigns work, orders skip-traces, cancels and finalizes requests, and manages filings. `Client` creates, documents, and submits its own requests. `Server` performs all field work. `Notary` notarizes affidavits and nothing else. Read access is broadly shared, but each list and detail read is still scoped to the caller's ownership where the role is entity-backed. In practice this ownership scoping on reads is applied only to the `Client` role: a `Client` reading or listing service requests, documents, assignments, services, affidavits, filings, or invoice lines sees only those whose `client_id` (directly or through the parent ServiceRequest) equals its `X-User-ID`. The `Server`, `Notary`, `Admin`, and `Dispatcher` roles are not ownership-filtered on reads — a `Server` may read any resource its role is authorized to read, regardless of whether it is the assigned server; the per-resource `server_id`/declarant ownership checks for those roles gate only the mutating actions enumerated above, never reads.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint explicitly states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system are "primary" resources that carry a standard set of system-managed fields:

- `id` — a unique, server-minted UUID. It carries no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on any mutation of the resource.
- `version` — an integer that begins at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control.

There is one deliberate exception. The `ServerTerritory` join resource — the record that grants a server coverage of a county — is immutable after creation. It carries only `id` and `created_at`; it has no `updated_at` and no `version` field. Every other entity in this specification (Client, County, Server, ServiceRequest, Document, Assignment, Attempt, Service, Affidavit, SkipTrace, Stakeout, Filing, and InvoiceLine) carries the full set including `updated_at` and `version`.

When a derived field changes as a side effect of some other action — for example, when a server's `reliability_score` is recomputed, or a request's `final_fee_cents` is recalculated — that constitutes a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address nested resources through multi-segment paths (for example, a stakeout under an assignment, or a document under a service request). The system validates the existence of each path identifier in strict left-to-right order. The first identifier in the path that does not resolve to an existing, correctly-scoped resource causes the request to be rejected immediately with `ERR_NOT_FOUND` (HTTP 404), before any later identifier or any body field is considered. Existence validation of path and body references always precedes business-rule evaluation.

### 2.6. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED` (401). Authorization is second: a role not permitted for the endpoint yields `ERR_UNAUTHORIZED` (403). Existence is third: any unresolved path or body reference yields `ERR_NOT_FOUND` (404). Request well-formedness is fourth, applied to all mutating endpoints: a missing required field, an invalid enum value, a `page_count` below 1, a non-numeric latitude or longitude, or a supplied-but-negative optional integer policy field (a County's `min_diligent_attempts`, `filing_fee_cents`, or `max_concurrent_filings`, or a Server's `max_active_assignments`) yields `ERR_INVALID_REQUEST` (422). A field whose value is a boolean where an integer is expected (or vice versa) is likewise malformed, since booleans are not accepted as integers. Fifth, on the single optimistic-concurrency-guarded create, a stale parent version yields `ERR_STALE_VERSION` (412). Sixth, on every state-transition endpoint, a target resource that is not in a state from which the requested transition is defined yields `ERR_INVALID_STATE` (409). Only after all of these pass does the system evaluate the domain-specific business rules described in Section 3 — diligence, segregation, territory, capacity, temporal, and fiscal checks — each of which carries its own error and is described alongside the workflow it guards.

### 2.7. Monetary Precision and Fee Rounding

All money in the system is expressed in whole cents as integers — `prepaid_balance_cents`, `filing_fee_cents`, `quoted_fee_cents`, `final_fee_cents`, the `amount_cents` of each invoice line, and the deposit `amount_cents` are all integer cent counts. Fees are assembled from individual invoice lines. The pinned rounding order is round-per-line-then-sum: each line amount is rounded up to a whole number of cents using the ceiling function at the line level, and the rounded line amounts are then summed. The system never sums fractional cents and rounds at the end; it always rounds each line first. The server reliability score is the only non-monetary computed number and uses a different rule, stated in Section 3: two decimal places, rounded half up, clamped to the inclusive range from 0 to 100.

### 2.8. The Logical Clock

The system operates on a logical clock rather than wall-clock time, so that deadlines, attempt timestamps, and filing windows are reproducible. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it returns precisely that default and never falls back to the host wall clock. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant and echoes back the new clock value as `now_utc`. All computed timestamps — a request's `deadline_utc`, the "current clock" against which an attempt's `attempted_at_utc` is validated — read from this logical clock.

### 2.9. Optimistic Concurrency Control

Exactly one operation in this system is guarded by optimistic concurrency control: offering a new assignment against a service request. The act of offering creates a new `OFFERED` assignment and legitimately supersedes any prior `OFFERED` assignment for the same request — a dispatcher may re-offer the work to a better-ranked server. Because that supersede advances the request's `version`, a dispatcher whose view of the request predates the supersede would be working from a stale picture. To prevent that, the offer request must carry `expected_service_request_version`, which is a required (non-optional) field carrying the client's last observed `version` of the target ServiceRequest. If `expected_service_request_version` does not equal the request's current `version`, the offer is rejected with `ERR_STALE_VERSION` (HTTP 412), and no assignment is created. No other endpoint accepts or requires a version field; only the assignment-offer create is version-guarded.

### 2.10. Cascading State Consistency

State changes in this system propagate across entity boundaries, both upward (a child event bubbling a parent forward) and downward (a parent cancellation cascading into children). The system performs these propagations automatically, without requiring a separate client call on each affected resource. When a server's first valid attempt is logged, the request moves itself from `ASSIGNED` to `IN_PROGRESS`. When service is recorded or non-est is declared, the governing assignment completes and the server's counters and reliability are recomputed. When a request is cancelled, the cascade reaches all the way down through the active assignment, into its scheduled stakeouts, into the invoice lines those stakeouts generated, and finally back up to the request's recomputed fee. Each entity touched in a cascade is independently mutated: its `updated_at` is refreshed and its `version` is incremented. The precise transitions, preconditions, and side effects of each cascade are specified in Section 3.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Clients, Counties, Servers, and Territories

Before any service can be requested, the platform's reference data must exist. An `Admin` or `Dispatcher` creates a **Client** by supplying a `firm_name` and a contact `email`. A new client begins with `status` set to `ACTIVE` and a `prepaid_balance_cents` of 0. Funds are added to a client through a deposit, which credits the supplied `amount_cents` onto the client's `prepaid_balance_cents` (the deposit amount is added to the running balance). Only an `Admin` may suspend or reactivate a client by setting its `status` through a `to_status` value of either `ACTIVE` or `SUSPENDED`; a `SUSPENDED` client cannot submit new requests.

Counties carry the jurisdiction rules that drive legality and pricing, and only an `Admin` may create one. A County is defined by its `name` and two-letter `state_code`, plus four optional policy fields that take documented defaults when omitted: `e_file_enabled` (whether the county accepts electronic filing, default false), `min_diligent_attempts` (the statutory minimum number of distinct-day attempts required before substitute or posting service or a non-est declaration is permitted, default 3), `filing_fee_cents` (the court filing fee charged for each accepted filing, default 4000), and `max_concurrent_filings` (the aggregate cap on how many filing e-file windows may overlap at any instant in the county, default 2).

A **Server** is the licensed process server who performs field work. An `Admin` or `Dispatcher` creates one with a `full_name` and a state `license_no`, and an optional `max_active_assignments` capacity that defaults to 5. A new server starts `ACTIVE`, with `active_assignment_count` and `completed_count` both at 0 and a `reliability_score` of 100. Three of those fields are system-maintained and never set directly by a caller: `active_assignment_count` is, by invariant, exactly the number of assignments in `ACTIVE` status whose `server_id` is this server; `completed_count` is the number whose status is `COMPLETED`; and `reliability_score` is the performance number recomputed on every terminal assignment transition. Only an `Admin` may suspend or reactivate a server by setting its `status` through a `to_status` of `ACTIVE` or `SUSPENDED`; only an `ACTIVE` server may receive offers or log attempts.

Coverage is the bridge between servers and counties. An `Admin` or `Dispatcher` grants a server coverage of a county by creating a **ServerTerritory**, supplying the `county_id`; the server is taken from the path. The join records `server_id` and `county_id`, and the pair must be unique — a server covers a county at most once. A create that names an already-covered `(server_id, county_id)` pair is idempotent: it returns the existing ServerTerritory row with `201 Created` rather than creating a duplicate or raising an error. A server's territories can be listed from the server's side, and the territories covering a county can be listed from the county's side; these reverse lookups are how a dispatcher confirms eligibility before offering work.

### 3.2. The Service Request: From Draft to the Offer Pool

The central order in the system is the **ServiceRequest**. A `Client` (for its own work) or a `Dispatcher` (on a client's behalf) creates one in `DRAFT` status by supplying the owning `client_id`, the `county_id` of the service address, the `recipient_name` of the person to be served, the `service_address`, and its `service_lat` and `service_lng` coordinates in decimal degrees. Two optional flags shape the job: `rush` (default false) marks an expedited job, and `skip_trace_requested` (default false) records that a skip-trace investigation was ordered. While the request is still in `DRAFT`, documents may be attached: a `Document` carries a `doc_type` — one of `SUMMONS`, `SUBPOENA`, `COMPLAINT`, `NOTICE`, or `WRIT` — and a `page_count` of at least 1, and it references its parent request through `service_request_id`. Documents may only be attached while the request is in `DRAFT`.

Submitting a request advances it from `DRAFT` to `SUBMITTED`, moving it into the offer pool. Two preconditions guard the submit: the owning client's `status` must be `ACTIVE`, or the submit is rejected with `ERR_CLIENT_SUSPENDED`; and at least one Document must already be attached, or it is rejected with `ERR_NO_DOCUMENT`. Submission triggers several side effects in one transaction. First, the deadline is fixed: `deadline_utc` is set to the request's `created_at` plus 48 hours when `rush` is true, otherwise `created_at` plus 30 days. Second, the provisional `quoted_fee_cents` is computed using the quoted variant of the fee calculation (Section 3.8). Third, the initial invoice lines are generated — a `BASE` line, a `PRINTING` line covering the documents' pages, a `RUSH` line if and only if `rush` is true, and a `SKIP_TRACE` line if and only if `skip_trace_requested` is true. Fourth, `final_fee_cents` is recomputed using the final variant over the lines that now exist.

While a request sits in the pool, a dispatcher may order a skip-trace and may begin offering it to servers. A **SkipTrace** is created by a `Dispatcher` against the request, optionally seeded with an array of `candidate_addresses` to investigate (the array may be empty, and defaults to empty). Its lifecycle is described in Section 3.7. The request's own status fields — `assignment_id` (the current non-superseded assignment, initially null), `service_type` (null until service is recorded), `distinct_attempt_days` (the count of distinct UTC calendar days bearing a non-superseded attempt, initially 0), `quoted_fee_cents`, and `final_fee_cents` — are all system-maintained and evolve as the workflow proceeds through the states `DRAFT`, `SUBMITTED`, `ASSIGNED`, `IN_PROGRESS`, `SERVED`, `NON_EST`, `FILED`, `COMPLETED`, and `CANCELLED`.

### 3.3. Offering, Accepting, and Reassigning Work

Offering work to a server is a dispatcher-only action that creates an **Assignment** in `OFFERED` status, referencing the request through `service_request_id` and the chosen server through `server_id`. The offer payload names the `server_id` and must carry `expected_service_request_version` — the optimistic-concurrency guard described in Section 2.9. The offered server must cover the request's county through an existing ServerTerritory row, or the offer is rejected with `ERR_OUTSIDE_TERRITORY`. A successful offer has two further effects: any prior `OFFERED` assignment for the same request is superseded — its status becomes `REASSIGNED` and its `superseded` flag becomes true — and the request's `version` is incremented by one. A stale `expected_service_request_version` (not equal to the request's current `version`) is rejected with `ERR_STALE_VERSION` before any of this occurs.

A server accepts its own offer. Acceptance is guarded by four checks. The supersession guard is evaluated first, ahead of the generic `OFFERED`-state check: a superseded assignment (which a prior re-offer left in `REASSIGNED` status with `superseded` true) is rejected with `ERR_ASSIGNMENT_SUPERSEDED`, taking precedence over the `ERR_INVALID_STATE` that its non-`OFFERED` status would otherwise produce. Once the assignment is confirmed `OFFERED` and not superseded, the remaining gates are checked in order: the server's `status` must be `ACTIVE` (else `ERR_SERVER_SUSPENDED`); the server's `active_assignment_count` must be strictly less than its `max_active_assignments` (else `ERR_SERVER_AT_CAPACITY`); and the acting `X-User-ID` must equal the assignment's `server_id` (else `ERR_UNAUTHORIZED`). On a valid accept, the assignment moves `OFFERED → ACCEPTED` and then immediately and automatically `ACCEPTED → ACTIVE` in the same operation. The auto-advance to `ACTIVE` increments the server's `active_assignment_count` by one, bubbles the request from `SUBMITTED` to `ASSIGNED` and sets its `assignment_id` to this assignment, and supersedes every other `OFFERED` assignment for the same request (each such assignment's status becomes `REASSIGNED` and its `superseded` flag becomes true). A server may instead decline its own `OFFERED` assignment, which moves it `OFFERED → DECLINED`; declining is permitted only for the owning server (else `ERR_UNAUTHORIZED`) and has no further side effects.

Dispatchers can pull an in-flight assignment back into the pool through reassignment. Reassigning moves the current `ACTIVE` assignment `ACTIVE → REASSIGNED`: the server's `active_assignment_count` is decremented by one (with no change to `completed_count`, since the work was not completed) and the server's `reliability_score` is recomputed; every attempt logged under that assignment is marked `superseded` true; and the request bubbles down from `ASSIGNED` or `IN_PROGRESS` back to `SUBMITTED` with its `assignment_id` cleared to null. The same return-to-pool effect — request to `SUBMITTED`, `assignment_id` to null, attempts under the leaving assignment marked superseded and `distinct_attempt_days` recomputed — applies whenever the current assignment leaves `ACTIVE` without completing, whether through reassignment or decline. Superseded attempts never count toward diligence.

### 3.4. Field Attempts, GPS, and Diligence

Once an assignment is `ACTIVE`, the server logs each visit as an **Attempt**. An attempt is created against the assignment and records the `attempted_at_utc` timestamp, the `gps_lat` and `gps_lng` coordinates in decimal degrees where the visit occurred, and an `outcome` that is one of `NO_ANSWER`, `EVADED`, `BAD_ADDRESS`, or `CONTACT_MADE`. The attempt also copies `service_request_id` from the assignment for filtered lookups, and carries a `superseded` flag (default false) that becomes true if the attempt's assignment is later reassigned or cancelled. Logging an attempt requires the assignment to be in `ACTIVE` status, or the attempt is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`; a suspended server cannot log attempts and is rejected with `ERR_SERVER_SUSPENDED`. The `attempted_at_utc` is validated only for ISO 8601 well-formedness (a non-string or unparseable value yields `ERR_INVALID_REQUEST`); it is otherwise accepted as supplied — there is no check that it is no later than the current logical clock and no check that it falls within the assignment's `ACTIVE` lifetime, and a future-dated attempt is recorded successfully. The first non-superseded attempt under a request moves it from `ASSIGNED` to `IN_PROGRESS`. Every attempt log recomputes the request's `distinct_attempt_days` and its `final_fee_cents`.

**Diligence** is the legal heart of this domain. The request's `distinct_attempt_days` counts the distinct UTC calendar days on which a non-superseded attempt was logged — two attempts on the same calendar day count once. A county's `min_diligent_attempts` sets the floor: substitute or posting service, and a non-est declaration, are all legally permitted only once `distinct_attempt_days` is at least the county's `min_diligent_attempts`. Falling short yields `ERR_DILIGENCE_NOT_MET`.

### 3.5. Recording Service and Declaring Non-Est

When the server effects service, they record a **Service** under the request, supplying the governing `assignment_id`, the `service_type` (one of `PERSONAL`, `SUBSTITUTE`, or `POSTING`), the `served_at_utc` timestamp of effective service, and, for substitute service, the `recipient_relation` describing the substitute recipient's relationship to the recipient (for example spouse or co-resident; it is empty for other service types). The `recipient_relation` field is optional on every service type — including `SUBSTITUTE` — and is not required for well-formedness; when omitted or null it defaults to the empty string, and supplying a non-string value yields `ERR_INVALID_REQUEST`. Recording service is permitted only by the server who owns the assignment.

Three preconditions branch by service type and timing. For `PERSONAL` service, the latest non-superseded attempt's `outcome` must be `CONTACT_MADE`, or the record is rejected with `ERR_NO_CONTACT_ATTEMPT`. For `SUBSTITUTE` or `POSTING` service, the request's `distinct_attempt_days` must be at least the county's `min_diligent_attempts`, or it is rejected with `ERR_DILIGENCE_NOT_MET`. And for a `rush` request, the `served_at_utc` must be on or before the request's `deadline_utc` (the boundary is inclusive — equality is allowed), or it is rejected with `ERR_DEADLINE_PASSED`.

A successful service recording moves the request `IN_PROGRESS → SERVED` and triggers a chain of effects. The request's `service_type` is set from the recorded service. A new **Affidavit** is created in `DRAFT` status, with its `declarant_server_id` set to the assignment's `server_id` and its `service_id` set to the new service's id. The governing assignment bubbles up `ACTIVE → COMPLETED`: the server's `active_assignment_count` is decremented by one, its `completed_count` is incremented by one, and its `reliability_score` is recomputed.

Alternatively, when a recipient cannot be found after diligent search, the server declares **non-est inventus**, moving the request `IN_PROGRESS → NON_EST`. This declaration is permitted only when `distinct_attempt_days` is at least the county's `min_diligent_attempts` (else `ERR_DILIGENCE_NOT_MET`). Declaring non-est completes the governing assignment exactly as a successful service does: the assignment moves `ACTIVE → COMPLETED`, the server's `active_assignment_count` is decremented by one, its `completed_count` is incremented by one, and its `reliability_score` is recomputed. A non-est request carries no affidavit and proceeds directly toward completion.

### 3.6. Stakeouts

A server working an `ACTIVE` assignment may schedule a **Stakeout** — a watched time window during which they wait for the recipient. The stakeout is created under the assignment with a `window_start_utc` (inclusive) and a `window_end_utc` (exclusive); the window is half-open, spanning from the start up to but not including the end. The stakeout copies its `server_id` from the assignment's server and begins in `SCHEDULED` status. A scheduling constraint protects the server's calendar: the new window must not overlap any other non-`CANCELLED` stakeout for the same server, though exact adjacency — one window's end equalling the next window's start — is allowed because the windows are half-open. An overlap is rejected with `ERR_STAKEOUT_OVERLAP`. Scheduling a stakeout generates a `STAKEOUT` invoice line and recomputes the request's `final_fee_cents`.

A stakeout's owning server may transition it. Setting it to `COMPLETED` (permitted only for the server who owns the parent assignment, else `ERR_UNAUTHORIZED`) closes the window with no further side effect. Setting it to `CANCELLED` — or having the system cancel it as part of a request-cancellation cascade — voids this stakeout's `STAKEOUT` invoice line (its `voided` flag becomes true) and recomputes the request's `final_fee_cents`. Both transitions move the stakeout out of `SCHEDULED`; the stakeout's `status` is one of `SCHEDULED`, `COMPLETED`, or `CANCELLED`.

### 3.7. Skip-Trace Investigation

A skip-trace locates a recipient whose whereabouts are uncertain. A `SkipTrace` begins in `REQUESTED` status, carries the `candidate_addresses` array it was seeded with, and exposes a `located_address` that is null until a successful location. A server progresses it. Moving from `REQUESTED` to `IN_PROGRESS` is unconditional. From `IN_PROGRESS` the trace branches.

The successful branch — `IN_PROGRESS → LOCATED` — requires that `candidate_addresses` be non-empty (else `ERR_NO_CANDIDATE_ADDRESS`) and that the request body supply a `located_address` that is a member of `candidate_addresses` (else `ERR_ADDRESS_NOT_CANDIDATE`). On success the trace's `located_address` is set to the supplied value, and as a divergent side effect the parent request's `service_address` is updated to that located address so subsequent attempts target the confirmed location. The unsuccessful branch — `IN_PROGRESS → NOT_LOCATED` — has no preconditions and performs no address mutation; the request's `service_address` is left untouched. The skip-trace `status` is one of `REQUESTED`, `IN_PROGRESS`, `LOCATED`, or `NOT_LOCATED`, and the latter two are terminal.

### 3.8. Affidavit, Notarization, and Separation of Duties

Every successfully served request produces an **Affidavit** — the sworn proof of service — created automatically in `DRAFT` status when service is recorded, as described in Section 3.5. The affidavit references the proving service through `service_id`, names the `declarant_server_id` (the server who effected service and will swear to it), and holds a `notary_user_id` that is null until notarization. Its `status` moves through `DRAFT`, `SIGNED`, `NOTARIZED`, `FILED`, and `VOID`.

The declarant server signs first, moving the affidavit `DRAFT → SIGNED`. Signing is permitted only when the acting `X-User-ID` equals the affidavit's `declarant_server_id`, the declarant; any other server is rejected with `ERR_UNAUTHORIZED`. Notarization is reserved to the `Notary` role and moves the affidavit `SIGNED → NOTARIZED`. Here the system enforces **separation of duties**: the notarizing `Notary`'s `X-User-ID` must differ from the affidavit's `declarant_server_id`, so that the server who swore the proof cannot also notarize it. A self-notarization attempt is rejected with `ERR_SEGREGATION_VIOLATION`. On a valid notarization, the affidavit's `notary_user_id` is set to the acting `X-User-ID`. The affidavit later moves `NOTARIZED → FILED` automatically when its filing is accepted (Section 3.9). The `DRAFT → VOID` transition exists for completeness and is reached only by system action.

### 3.9. County Filing and the E-File Window

Once a request is `SERVED` and its affidavit notarized, a dispatcher files the proof with the county court. A **Filing** is created by a `Dispatcher` against the served request, supplying the `affidavit_id` of the proof to be filed and the e-file submission window's `window_start_utc` (inclusive) and `window_end_utc` (exclusive, half-open). The create itself imposes no request-state or affidavit-state precondition — it does not require the request to be `SERVED` or the affidavit to be `NOTARIZED` (those gates are enforced only on the `PENDING → SUBMITTED` transition below); the only structural check beyond existence is that the named affidavit belongs to this request, and an `affidavit_id` resolving to an affidavit under a different request yields `ERR_NOT_FOUND`. The filing copies its `county_id` from the request, starts in `PENDING` status, and carries a `reject_count` (initially 0) and a `status` that is one of `PENDING`, `SUBMITTED`, `ACCEPTED`, or `REJECTED`.

Submitting a filing — `PENDING → SUBMITTED` — is the most heavily guarded transition in the system, and the checks read in order. The request must be in `SERVED` status (else `ERR_INVALID_STATE`). The linked affidavit must be in `NOTARIZED` status (else `ERR_AFFIDAVIT_NOT_NOTARIZED`). The county's `e_file_enabled` must be true (else `ERR_EFILE_NOT_ENABLED`). And the filing's e-file window must respect the county's aggregate concurrency cap: the half-open window from `window_start_utc` to `window_end_utc` may overlap strictly fewer than the county's `max_concurrent_filings` other `SUBMITTED` filing windows in that county — equivalently, it may overlap at most `max_concurrent_filings` minus one of them — or it is rejected with `ERR_FILING_WINDOW_FULL`. A successful submit generates a `FILING` invoice line equal to the county's `filing_fee_cents` and recomputes the request's `final_fee_cents`.

From `SUBMITTED`, a filing branches three ways, each driven by a dispatcher. Acceptance — `SUBMITTED → ACCEPTED` — bubbles the request up `SERVED → FILED` and moves the affidavit `NOTARIZED → FILED`. Rejection — `SUBMITTED → REJECTED` — voids this filing's `FILING` invoice line and recomputes `final_fee_cents`. And a rejected filing may be resubmitted — `REJECTED → SUBMITTED`, the reject-and-resubmit loop — which again requires the linked affidavit to be `NOTARIZED` (else `ERR_AFFIDAVIT_NOT_NOTARIZED`) and again requires the window to overlap fewer than `max_concurrent_filings` other `SUBMITTED` windows (else `ERR_FILING_WINDOW_FULL`); a successful resubmit increments `reject_count` by one, regenerates the `FILING` invoice line, and recomputes `final_fee_cents`.

### 3.10. Cancellation and the Four-Level Cascade

A dispatcher may cancel a request from several non-terminal states. From `DRAFT`, cancellation moves the request straight to `CANCELLED` with no side effects. From `SUBMITTED`, cancellation marks every `OFFERED` assignment for the request `DECLINED` and then moves the request to `CANCELLED`.

Cancelling a request that has reached `ASSIGNED` or `IN_PROGRESS` is the cascade root, and the effects propagate four levels deep. At level one, the current `ACTIVE` assignment is cancelled (`ACTIVE → CANCELLED`). At level two, that assignment cancellation decrements the server's `active_assignment_count` by one and recomputes the server's `reliability_score`, and transitions every `SCHEDULED` stakeout under that assignment to `CANCELLED`. At level three, each cancelled stakeout voids its `STAKEOUT` invoice line (the line's `voided` flag becomes true). At level four, the request's `final_fee_cents` is recomputed over the surviving non-voided lines. The same four-level cascade applies whether cancellation begins from `ASSIGNED` or from `IN_PROGRESS`. `COMPLETED` and `CANCELLED` are the request's terminal states.

### 3.11. Completion and Fiscal Settlement

A request reaches the billing settlement from one of two penultimate states. A `FILED` request (its proof accepted by the county) or a `NON_EST` request (its recipient unfindable after diligence) is finalized by a dispatcher. Completing a `FILED` request requires the request to be in `FILED` status (else `ERR_INVALID_STATE`); completing a `NON_EST` request requires it to be in `NON_EST` status. On completion the request's `final_fee_cents` is recomputed one last time under the final variant and frozen, and the owning client's `prepaid_balance_cents` is debited by that frozen `final_fee_cents`. The debit is gated on funds: if the client's `prepaid_balance_cents` is less than `final_fee_cents`, completion is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402) and no debit occurs. A successful completion moves the request to `COMPLETED`.

### 3.12. Fee Composition and Invoice Lines

Every billable event in a request's life produces an **InvoiceLine** referencing the request through `service_request_id`. A line has a `kind` — one of `BASE`, `RUSH`, `ATTEMPT`, `SKIP_TRACE`, `STAKEOUT`, `FILING`, or `PRINTING` — an `amount_cents` already rounded to whole cents at the line level, and a `voided` flag (default false) that excludes the line from totals once its underlying billable is cancelled or superseded. The request's `quoted_fee_cents` and `final_fee_cents` are two views of the same fee formula computed over different inputs.

The fee is built from these per-line amounts, each rounded up to whole cents at the line level and then summed. The base line is a flat 75 dollars (7,500 cents). The printing line is the total page count across all of the request's documents multiplied by 25 cents per page, rounded up to whole cents. The rush line is 50 dollars (5,000 cents) when the request is `rush`, otherwise zero. The skip-trace line is 90 dollars (9,000 cents) when a skip-trace was requested, otherwise zero.

Per-attempt labor is tiered. Let the billable attempt count be the number of qualifying attempts (defined per variant below). The first 1 billable attempt is free. The next tier — attempts beyond the first free one, up through the third attempt — is charged at 25 dollars (2,500 cents) each. Attempts beyond the third are charged at 40 dollars (4,000 cents) each. Concretely, the count of attempts billed at the first rate is the count of attempts up to and including the third, less the one free attempt, but never below zero; the count billed at the second rate is the count of attempts beyond the third, never below zero. The attempt line is the first-rate count multiplied by 2,500 cents plus the second-rate count multiplied by 4,000 cents. The stakeout line is 120 dollars (12,000 cents) for each non-voided stakeout. The filing line is the sum of the amounts of the non-voided `FILING` invoice lines, which equals the county's `filing_fee_cents` for each submitted-or-accepted filing.

The running subtotal is the sum of the base, printing, rush, skip-trace, attempt, stakeout, and filing lines. Then a rush uplift is applied as an explicit ordered step, and only when the request is `rush`: it applies solely to the labor lines — the attempt line plus the stakeout line — at a multiplier of 1.5. The uplift is the labor total multiplied by 0.5 (that is, the multiplier of 1.5 minus 1), rounded up to whole cents, and is added to the subtotal. This rush uplift is computed after tiering, never before. The resulting subtotal is the fee in cents.

The two variants differ only in their inputs. The **quoted** variant is computed at submission into `quoted_fee_cents`: its billable attempt count is fixed at 0 (no attempts exist yet at submission), and its stakeout and filing lines are absent. It is a forward-looking estimate derived from the request's flags and documents alone. The **final** variant is recomputed into `final_fee_cents` on every billable side effect and frozen at completion: its billable attempt count is the number of attempts whose `superseded` flag is false under the request's non-superseded assignments, regardless of outcome; its stakeout line covers each stakeout whose status is `SCHEDULED` or `COMPLETED` (`CANCELLED` stakeouts are excluded); and its filing line covers the non-voided `FILING` lines.

### 3.13. Server Reliability Scoring

A server's `reliability_score` is a performance number in the inclusive range from 0 to 100, recomputed on every terminal assignment transition for that server — that is, whenever one of the server's assignments reaches `COMPLETED`, `REASSIGNED`, or `CANCELLED`. The computation looks across all assignments whose `server_id` is this server and tallies three counts. The served count is the number of the server's `COMPLETED` assignments whose request reached `SERVED`. The non-est count is the number of `COMPLETED` assignments whose request reached `NON_EST`. The walked count is the number of assignments whose status is `REASSIGNED` or `CANCELLED`.

The "good work" total weights a served assignment at 1.0 and a non-est assignment at 0.5: it is the served count multiplied by 1.0 plus the non-est count multiplied by 0.5. The raw score is 100 multiplied by that good-work total, divided by a base pool, where the divisor is taken as the larger of 1 and the base pool to avoid division by zero. The result is then clamped to a maximum of 100, rounded half up to two decimal places, and clamped to the inclusive range from 0 to 100.

The base pool depends on the variant. The **realized** variant — the one persisted in the server's `reliability_score` — uses a base pool of the served count plus the non-est count plus the walked count, counting only resolved, terminal assignments and ignoring in-flight `ACTIVE` work. The **projected** variant — returned by the dispatch-ranking read described below — uses a base pool of the served count plus the non-est count plus the walked count plus the server's `active_assignment_count`, treating in-flight `ACTIVE` assignments as not-yet-good work. The projected score is therefore always less than or equal to the realized score, and diverges from it precisely when `active_assignment_count` is greater than zero. A computed read returns the server's `realized_score`, its `projected_score`, and its current `active_assignment_count` together so a dispatcher can rank servers for a new offer.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions, deposits, and clock-setting — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |
| POST | `/clients` | Create a Client (law firm) | Admin, Dispatcher |
| GET | `/clients/{id}` | Get a Client | Admin, Dispatcher, Client |
| POST | `/clients/{id}/deposits` | Add prepaid funds to a Client | Admin, Dispatcher |
| POST | `/clients/{id}/state` | Suspend or reactivate a Client | Admin |
| POST | `/counties` | Create a County jurisdiction config | Admin |
| GET | `/counties/{id}` | Get a County | Admin, Dispatcher, Server |
| POST | `/servers` | Create a process Server | Admin, Dispatcher |
| GET | `/servers/{id}` | Get a Server | Admin, Dispatcher, Server |
| POST | `/servers/{id}/state` | Suspend or reactivate a Server | Admin |
| GET | `/servers/{id}/reliability-projection` | Projected reliability for dispatch ranking | Admin, Dispatcher |
| POST | `/servers/{id}/territories` | Grant a Server coverage of a County | Admin, Dispatcher |
| GET | `/servers/{id}/territories` | List a Server's territories | Admin, Dispatcher, Server |
| GET | `/counties/{id}/territories` | List ServerTerritory rows covering a County | Admin, Dispatcher |
| GET | `/assignments` | List Assignments; filter by `server_id` or `service_request_id` | Admin, Dispatcher, Server |
| POST | `/service-requests` | Create a ServiceRequest (DRAFT) | Client, Dispatcher |
| GET | `/service-requests/{id}` | Get a ServiceRequest | Admin, Dispatcher, Client, Server |
| GET | `/service-requests` | List ServiceRequests; filter by `client_id`, `county_id`, `assignment_id`, `status` | Admin, Dispatcher, Client |
| POST | `/service-requests/{id}/documents` | Attach a Document (DRAFT only) | Client, Dispatcher |
| GET | `/service-requests/{id}/documents` | List Documents for a request | Admin, Dispatcher, Client, Server |
| POST | `/service-requests/{id}/submit` | Submit a DRAFT request to the offer pool | Client, Dispatcher |
| POST | `/service-requests/{id}/skip-traces` | Order a SkipTrace for the request | Dispatcher |
| GET | `/service-requests/{id}/skip-traces` | List SkipTraces for a request | Admin, Dispatcher, Server |
| POST | `/service-requests/{id}/assignments` | Offer the request to a Server (OCC-guarded) | Dispatcher |
| GET | `/service-requests/{id}/assignments` | List Assignments for a request | Admin, Dispatcher, Client, Server |
| POST | `/service-requests/{id}/reassign` | Pull the active/offered assignment | Dispatcher |
| POST | `/service-requests/{id}/services` | Record effective service | Server |
| GET | `/service-requests/{id}/services` | List Services for a request | Admin, Dispatcher, Client, Server |
| GET | `/assignments/{id}/services` | List Services effected under an assignment | Admin, Dispatcher, Client, Server |
| POST | `/service-requests/{id}/non-est` | Mark request NON_EST | Server |
| POST | `/service-requests/{id}/cancel` | Cancel a request (cascade root) | Dispatcher |
| POST | `/service-requests/{id}/complete` | Finalize a FILED or NON_EST request; freeze fee; debit client | Dispatcher |
| GET | `/service-requests/{id}/invoice-lines` | List InvoiceLines for a request | Admin, Dispatcher, Client |
| GET | `/assignments/{id}` | Get an Assignment | Admin, Dispatcher, Server |
| POST | `/assignments/{id}/accept` | Accept an OFFERED assignment (auto-advances to ACTIVE) | Server |
| POST | `/assignments/{id}/state` | Decline an OFFERED assignment | Server |
| POST | `/assignments/{id}/attempts` | Log a service Attempt | Server |
| GET | `/assignments/{id}/attempts` | List Attempts for an assignment | Admin, Dispatcher, Client, Server |
| GET | `/service-requests/{id}/attempts` | List non-superseded Attempts across a request | Admin, Dispatcher, Server |
| POST | `/assignments/{id}/stakeouts` | Schedule a Stakeout under an ACTIVE assignment | Server |
| GET | `/assignments/{id}/stakeouts` | List Stakeouts for an assignment | Admin, Dispatcher, Server |
| GET | `/servers/{id}/stakeouts` | List a Server's Stakeouts across assignments | Admin, Dispatcher, Server |
| POST | `/stakeouts/{id}/state` | Transition a Stakeout (COMPLETED or CANCELLED) | Server |
| GET | `/skip-traces/{id}` | Get a SkipTrace | Admin, Dispatcher, Server |
| POST | `/skip-traces/{id}/state` | Transition a SkipTrace | Server |
| GET | `/affidavits/{id}` | Get an Affidavit | Admin, Dispatcher, Client, Server, Notary |
| GET | `/service-requests/{id}/affidavits` | List Affidavits for a request; filter by `service_id` | Admin, Dispatcher, Client, Server, Notary |
| GET | `/affidavits` | List Affidavits; filter by `declarant_server_id` or `service_id` | Admin, Dispatcher, Notary, Server |
| POST | `/affidavits/{id}/sign` | Declarant Server signs the affidavit | Server |
| POST | `/affidavits/{id}/notarize` | Notary notarizes a SIGNED affidavit | Notary |
| POST | `/service-requests/{id}/filings` | Create a Filing for a SERVED request's affidavit | Dispatcher |
| GET | `/service-requests/{id}/filings` | List Filings for a request; filter by `affidavit_id` | Admin, Dispatcher, Client |
| GET | `/filings` | List Filings; filter by `county_id`, `affidavit_id`, or `status` | Admin, Dispatcher |
| GET | `/filings/{id}` | Get a Filing | Admin, Dispatcher |
| POST | `/filings/{id}/state` | Transition a Filing (SUBMITTED/ACCEPTED/REJECTED/resubmit) | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CLIENT_SUSPENDED` | 409 Conflict |
| `ERR_NO_DOCUMENT` | 409 Conflict |
| `ERR_SERVER_SUSPENDED` | 409 Conflict |
| `ERR_SERVER_AT_CAPACITY` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ASSIGNMENT_SUPERSEDED` | 409 Conflict |
| `ERR_OUTSIDE_TERRITORY` | 409 Conflict |
| `ERR_NO_CONTACT_ATTEMPT` | 409 Conflict |
| `ERR_DILIGENCE_NOT_MET` | 409 Conflict |
| `ERR_DEADLINE_PASSED` | 409 Conflict |
| `ERR_STAKEOUT_OVERLAP` | 409 Conflict |
| `ERR_AFFIDAVIT_NOT_NOTARIZED` | 409 Conflict |
| `ERR_SEGREGATION_VIOLATION` | 409 Conflict |
| `ERR_EFILE_NOT_ENABLED` | 409 Conflict |
| `ERR_FILING_WINDOW_FULL` | 409 Conflict |
| `ERR_NO_CANDIDATE_ADDRESS` | 409 Conflict |
| `ERR_ADDRESS_NOT_CANDIDATE` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |

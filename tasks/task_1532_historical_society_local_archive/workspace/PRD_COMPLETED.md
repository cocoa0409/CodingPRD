# Historical Society Archive API — Product Requirements Document

## 1. Introduction

A county historical society carries a dual obligation: it is the legal custodian of donated materials and the public's doorway to them. Materials arrive as accession lots whose terms are fixed by deeds of gift; they are cataloged into collections, described by published finding aids, conserved when fragile, digitized by volunteers, and — only when every donor-imposed and statutory condition is satisfied — made available to researchers in a supervised reading room or through paid reproduction. This document specifies the API through which the society's staff, board, volunteers, and registered researchers perform that work.

The requirements below place particular weight on the audit chain. Donor restrictions such as reproduction prohibitions, publication-license mandates, embargoes, and verbatim citation text must survive amendment cycles and be enforced at the moment an order is placed or delivered. Deaccessioning follows board governance with segregation of duties and a mandatory cooling-off period before disposal. Environmental telemetry from storage zones continuously gates item availability, and every temporal judgment in the system — embargoes, cooling-off windows, no-show strike windows, future-start checks — reads a single server-side logical clock rather than wall-clock time, so that the record of decisions is deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to each operation is restricted by role; a caller whose role is not in the endpoint's authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes eight roles: `Registrar`, `Archivist`, `ReadingRoomStaff`, `BoardOfficer`, `VolunteerCoordinator`, `Volunteer`, `Researcher`, and `SystemAdmin`. A non-empty `X-User-Role` value outside these eight appears in no endpoint's authorized list and is therefore rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The identity semantics of `X-User-ID` differ by role and are part of the contract. When `X-User-Role` is `Researcher`, `X-User-ID` is the `id` of the acting `Researcher` record; ownership checks on any resource that references a researcher — a research request, a reading-room appointment, a reproduction order — compare the resource's `researcher_id` field to `X-User-ID`. A `Researcher` caller whose `X-User-ID` does not resolve to a registered researcher record is rejected with `ERR_NOT_FOUND`, and this caller resolution is the endpoint's first resource lookup, ahead of the request's other resource identifiers. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `proposed_by_user_id` on a deaccession proposal) but does not compare it to any entity's `id`. When `X-User-Role` is `BoardOfficer`, `X-User-ID` is likewise an opaque operator identifier, recorded as `approved_by_user_id` when the officer approves a deaccession proposal, and it is compared against `proposed_by_user_id` only for the segregation-of-duties check. When `X-User-Role` is `Volunteer`, `X-User-ID` is an opaque operator identifier recorded as `claimed_by_user_id` on digitization tickets, and ticket-level ownership checks compare that field to `X-User-ID`. When `X-User-Role` is `Archivist`, `ReadingRoomStaff`, `VolunteerCoordinator`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It records the server's wall-clock time at receipt of the request; it does not read the logical clock of §2.5.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field; an operation returns the resource its path addresses — deed execution and voiding return the deed, ticket claim-next returns the claimed ticket, and posting an environmental reading returns the updated zone (§2.6).
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

Failures below the resource contract still carry this error envelope: an unknown path is rejected with `ERR_NOT_FOUND` (404), an unsupported method on a known path with `ERR_INVALID_REQUEST` (405), and a request body that is not valid JSON or not a JSON object with `ERR_INVALID_REQUEST` (400).

---

### 2.3. Pagination and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted and must lie between 1 and 100 inclusive. The `offset` parameter specifies the number of items to skip and defaults to 0; it may not be negative. A `limit` outside the inclusive 1-to-100 range or a negative `offset` is rejected with `ERR_INVALID_PAGINATION_PARAMETERS`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties in creation timestamp broken by insertion order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

Beyond pagination, list endpoints accept resource-scoped filter query parameters that double as reverse-reachability views across the archive's relationships. Storage zones filter by `posture`. Collections filter by `parent_collection_id`, `storage_zone_id`, and `status`. Accessions, volunteer projects, researchers, and deaccession proposals filter by `status`. Items filter by `accession_id`, `collection_id`, and `status`. Finding aids filter by `collection_id` and `status`; oral histories use the same two filters. Digitization tickets filter by `project_id`, `item_id`, and `status`. Research requests filter by `researcher_id` and `status`. Reading-room appointments filter by `researcher_id`, `research_request_id`, `scheduled_date`, `room_code`, and `status`. Reproduction orders filter by `researcher_id`, `research_request_id`, and `status`.

### 2.4. Common Resource Properties

Every resource in the system — storage zones, collections, accessions, deeds of gift, items, conservation assessments, finding aids, volunteer projects, digitization tickets, researchers, research requests, reading-room appointments, reproduction orders, deaccession proposals, and oral-history recordings — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix. An `id` serves identity only and is never itself a decision input.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, stamped from the logical clock of §2.5 when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, restamped from the logical clock upon every modification of the resource.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascades originating elsewhere.

### 2.5. The Logical Clock and Scheduled Sweeps

All time-sensitive judgments in the archive — donor embargoes, the deaccession cooling-off window, the no-show strike window, appointment future-start checks, oral-history embargoes — read a single server-side **logical clock**, never wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter.

The clock is driven exclusively through a `SystemAdmin`-only capability, `POST /_clock/set_current_utc`, whose request body carries a `to_iso8601` instant. The logical clock is set to that instant and may move forward or backward; this freedom is pinned behavior. The response body carries `current_utc`, echoing the posted `to_iso8601` string verbatim; an instant posted with an offset is converted to UTC for all clock judgments, and a naive instant carrying no offset is interpreted as UTC. Setting the clock also performs a scheduled sweep: every deaccession proposal in `APPROVED` status whose `finalize_not_before` instant has been reached or passed by the new logical time transitions to `COOLED_OFF`. The sweep performs no other transitions, and moving the clock backward never reverses a transition that has already occurred.

### 2.6. Environmental Telemetry and Zone Posture

Each storage zone is defined by a unique `zone_code` (a duplicate code is rejected with `ERR_ZONE_CODE_EXISTS`), a human-readable `name`, and four configurable thresholds that govern breach detection: `temp_high_c` (default 24.0), `temp_low_c` (default 14.0), `humidity_high_pct` (default 60.0), and `humidity_low_pct` (default 30.0). A newly created zone begins with `posture` `OPEN`, a `breach_streak` of zero, and an empty `recent_readings` log.

Environmental readings arrive through a sensor-feed ingestion operation shared by `SystemAdmin` and `Archivist`, carrying `recorded_at`, `temperature_c`, and `humidity_pct`. Each reading is appended to the zone's `recent_readings` — an append-only embedded log whose elements carry `reading_id`, `recorded_at`, `temperature_c`, `humidity_pct`, and two booleans computed at posting time against the zone's current thresholds: `is_breach` and `is_severe`. A reading is a breach when its temperature is strictly greater than `temp_high_c`, strictly less than `temp_low_c`, its humidity is greater than or equal to `humidity_high_pct`, or its humidity is less than or equal to `humidity_low_pct`; note the deliberate asymmetry — the temperature bounds are strict comparisons while the humidity bounds are inclusive. A reading is severe when its temperature is greater than or equal to `temp_high_c` plus 4.0 degrees, or its humidity is greater than or equal to `humidity_high_pct` plus 15.0 percentage points; a severe reading is always also a breach. Thresholds are compared at the exact decimal precision posted.

After every reading is appended, the zone's posture is recomputed by a **deterministic replay** over the whole `recent_readings` log, ordered by `recorded_at` ascending with ties broken by the reading's own creation timestamp ascending and any remaining ties — readings posted at the same logical instant — broken by posting order — never by arrival order, so a late-arriving reading is inserted in timestamp order and rewrites history. The replay walks the ordered log maintaining a trailing breach run and a trailing in-range run, starting from an `OPEN` posture. A severe reading forces the posture to `CLOSED`, extends the breach run by one, and resets the in-range run. A non-severe breach extends the breach run and resets the in-range run; when the breach run reaches six the posture becomes `CLOSED`, and when the breach run reaches three while the replayed posture is still `OPEN` it becomes `RESTRICTED` — one or two consecutive breaches change nothing, a deliberate hysteresis. An in-range reading extends the in-range run and resets the breach run to zero; when the in-range run reaches three, the posture steps one level toward `OPEN` (`CLOSED` to `RESTRICTED`, `RESTRICTED` to `OPEN`, `OPEN` remaining `OPEN`). A zone therefore never recovers from `CLOSED` directly to `OPEN` in a single step; recovery proceeds one level at a time. When the replay finishes, its final posture becomes the zone's `posture` and the trailing breach run becomes `breach_streak` (zero whenever the latest ordered reading is in range). Reading the zone back returns `posture`, `breach_streak`, and `recent_readings` along with the zone's configured fields, with `recent_readings` serialized in the replay order just described; the ingestion response itself is this updated zone object.

Posture transitions fire cascades into the collections housed in the zone. When a zone leaves `OPEN` for `RESTRICTED`, or is driven from `OPEN` straight to `CLOSED` by a severe latest reading, every item whose collection sits in that zone and whose status is `AVAILABLE` moves to `ZONE_HOLD`, and every reading-room appointment in `CONFIRMED` status whose `scheduled_date` falls on or after the current logical date and whose underlying research request references a just-held item moves to `NEEDS_RESCHEDULE`. A zone moving from `RESTRICTED` to `CLOSED` on a six-breach run causes no further item transitions; already-held items remain `ZONE_HOLD`. When a zone returns to `OPEN`, the zone's `ZONE_HOLD` items become `AVAILABLE` again — but appointments in `NEEDS_RESCHEDULE` are deliberately **not** auto-restored; the researcher must explicitly reschedule or cancel them. This asymmetry is pinned product behavior.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, because each of them legitimately supersedes an existing record and therefore cannot be guarded by state checks alone.

Executing a deed of gift — `POST /deeds/{id}/execute` — requires the request body to carry `expected_accession_version`, a non-optional field holding the caller's last-observed `version` of the owning accession. If the accession's current `version` does not match, the execution is rejected with `ERR_STALE_VERSION` (HTTP 412). Executing one deed legitimately supersedes the previously executed deed, so a second execution carrying a stale expectation cannot be rejected from state alone; the stale-version check is what rejects it.

Creating a conservation assessment — `POST /items/{id}/conservation-assessments` — likewise requires a non-optional `expected_item_version` carrying the caller's last-observed `version` of the item, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A newer assessment legitimately supersedes the item's previous draft or approved assessment, so here too the stale-version check is the sole guard against a writer acting on an observation it has not refreshed.

Endpoints not named above do not take a version field; no other operation participates in optimistic concurrency control.

### 2.8. Validation Priority Order

When a request violates several rules at once, the error surfaced is determined by a fixed, system-wide priority order. Checks are evaluated in the following sequence, and the first failing tier determines the response:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization** — the caller's role appears in the endpoint's authorized list, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Request body shape**, validated before any resource lookup — required fields are present; enum values fall in their declared sets; time ranges are coherent (an appointment's `start_time` strictly precedes its `end_time`, and a recording's `session_start` strictly precedes its `session_end`); logged hours are a positive multiple of 0.25; item-id arrays are duplicate-free; a research request carries at least one and no more than ten item ids (more than ten yields `ERR_TOO_MANY_ITEMS`); a reproduction order's item array is non-empty (`ERR_ITEM_NOT_IN_REQUEST`); and pagination parameters on list endpoints obey their ranges (`ERR_INVALID_PAGINATION_PARAMETERS`). All other shape failures yield `ERR_INVALID_REQUEST`.
4. **Existence** — resource identifiers resolve, path identifiers first in left-to-right order, then body-referenced identifiers, else `ERR_NOT_FOUND`.
5. **Target state** — the target resource's own state machine permits the operation, else `ERR_INVALID_STATE`.
6. **Optimistic concurrency** — the `expected_accession_version` or `expected_item_version` matches the parent's current `version`, else `ERR_STALE_VERSION`.
7. **Cross-entity state gates** — the accession is `ACCESSIONED` for item creation and make-available (`ERR_ACCESSION_NOT_ACCESSIONED`); the collection is `ACTIVE` for item creation and finding-aid creation (`ERR_INVALID_STATE`); the collection has a published finding aid for make-available (`ERR_FINDING_AID_NOT_PUBLISHED`); the collection's zone posture is `OPEN` for make-available (`ERR_ZONE_RESTRICTED`); every referenced item is `AVAILABLE` for request creation, ticket creation, and rescheduling (`ERR_ITEM_NOT_AVAILABLE`); the referenced research request is `APPROVED` for appointment and reproduction-order creation (`ERR_REQUEST_NOT_APPROVED`); the researcher is `ACTIVE` for request, appointment, and order creation (`ERR_RESEARCHER_SUSPENDED`).
8. **Conservation and compliance gates** — fragile items may not be pulled to the reading room (`ERR_ITEM_TOO_FRAGILE`); the deaccession approver differs from the proposer (`ERR_SEGREGATION_OF_DUTIES`); the quality-control reviewer differs from the ticket claimant (`ERR_QC_SELF_REVIEW`); an active deed embargo blocks reproduction-order creation (`ERR_EMBARGO_ACTIVE`); a deed's reproduction restriction blocks order creation (`ERR_DEED_REPRODUCTION_RESTRICTED`); a deed's publication-license requirement blocks `PERSONAL`-class orders (`ERR_PUBLICATION_LICENSE_REQUIRED`); oral-history publication requires a signed release (`ERR_RELEASE_FORM_MISSING`) past any embargo (`ERR_ORAL_HISTORY_EMBARGOED`); a delivery's citation acknowledgment must contain the current deed's required citation text (`ERR_CITATION_MISMATCH`).
9. **Temporal gates** — an appointment's start is strictly in the future (`ERR_APPOINTMENT_IN_PAST`); a no-show may be recorded only once the appointment has ended (`ERR_APPOINTMENT_NOT_ENDED`); a deaccession finalize before the cooling-off instant fails (`ERR_COOLING_OFF_NOT_ELAPSED`).
10. **Constraint gates** — reading-room seat capacity and item double-booking (`ERR_APPOINTMENT_CAPACITY_EXCEEDED`, `ERR_ITEM_DOUBLE_BOOKED`); the recording-studio turnaround buffer (`ERR_RECORDING_ROOM_CONFLICT`); uniqueness (`ERR_COLLECTION_CODE_EXISTS`, `ERR_ZONE_CODE_EXISTS`, `ERR_DUPLICATE_EMAIL`); collection-hierarchy acyclicity (`ERR_COLLECTION_CYCLE`); the per-volunteer hour cap (`ERR_VOLUNTEER_HOUR_CAP_EXCEEDED`); a non-empty claim pool (`ERR_NO_CLAIMABLE_TICKETS`); project close with zero active tickets (`ERR_ACTIVE_TICKETS_REMAIN`); deaccession approval or finalization while a proposed item is in treatment (`ERR_ITEMS_IN_TREATMENT`); the release signer matching the narrator (`ERR_NARRATOR_MISMATCH`).
11. **Referential integrity and ownership** — an appointment or reproduction order may reference only a research request owned by the caller (`ERR_REQUEST_OWNERSHIP_MISMATCH`); cancellations, ticket actions, and hour logging are restricted to the owning researcher or volunteer (`ERR_OWNERSHIP_MISMATCH`); an order's items must be a subset of the request's items (`ERR_ITEM_NOT_IN_REQUEST`).
12. **Fiscal gates** — the annual page quota at invoice time (`ERR_REPRO_QUOTA_EXCEEDED`); exact payment amounts (`ERR_PAYMENT_AMOUNT_MISMATCH`); the requote threshold (`ERR_REQUOTE_REQUIRED`); complete hammer prices for a sale (`ERR_HAMMER_PRICE_MISSING`).

Each error carries the HTTP status listed in the §5 catalogue, regardless of the tier that surfaces it.

### 2.9. Precision, Rounding, and Monetary Conventions

All monetary amounts are integer cents — appraised values, fees, license flats, hammer prices, proceeds, and charged totals alike. Every fee and proceeds computation rounds **half up** to whole cents, and rounding steps are pinned per calculation in §3: the reproduction fee rounds at exactly two steps (the image-component multiplication and the discount multiplication), and deaccession proceeds round per item line before summing. Priority scores — conservation and digitization — are carried to exactly 2 decimal places, rounded half up; the fragile-adjusted urgency term is rounded half up to a whole number before entering the weighted score. Volunteer hours must be positive multiples of 0.25 and are stored exactly as posted. Environmental thresholds are compared at the exact decimal precision posted, with the strict-versus-inclusive asymmetry of §2.6 preserved. Clock times on appointments and studio sessions are compared at minute precision; appointment dates are interpreted as UTC calendar dates.

### 2.10. Consistency Model and Cascading Side Effects

The archive observes **immediate consistency**: every mutation, including every cascade a mutation triggers, is visible in the state returned by the triggering request. There is no deferred propagation. Derived rollups are recomputed synchronously on each event that can change them — a collection's `item_count` and `published_finding_aid_present`, a project's `active_ticket_count`, `hours_logged_total`, and `volunteer_hours`, a researcher's `no_show_strikes` and `total_charged_cents`. Rollups span direct children only: a collection's `item_count` counts the items that reference it directly, and the contents of subcollections are never rolled up into a parent — this is pinned.

Several cascades fan out across the archive and are specified fully in §3 alongside the workflows that trigger them: a zone leaving `OPEN` pushes its `AVAILABLE` items into `ZONE_HOLD` and future confirmed appointments referencing those items into `NEEDS_RESCHEDULE`; a researcher's suspension cancels their future confirmed appointments; deaccession finalization chains through items, research requests, appointments, digitization tickets, reproduction orders, collections, and finding aids; and a collection whose last non-deaccessioned direct item leaves the holdings deaccessions itself, retiring its published finding aids. Whenever a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments like any other mutation.

### 2.11. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially, left to right, before any body-referenced identifier is examined. The first path identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND`, and the error message names the resource type that failed to resolve. This applies to deeds drafted under an accession, conservation assessments created under an item, and tickets queued under a volunteer project alike: a request naming a non-existent accession, item, or project never reaches the child-level checks. Body-referenced identifiers — a collection, an accession, a research request, an item inside an `item_ids` array — are validated after the path identifiers, in the order the body presents them. On nested list endpoints, pagination-parameter validation precedes the path-identifier existence check for an accession's deed list and an item's conservation-assessment list, but follows it for the three item-scoped reverse views (`/items/{id}/research-requests`, `/items/{id}/reproduction-orders`, `/items/{id}/deaccession-proposals`), where a non-existent item rejects with `ERR_NOT_FOUND` even when the pagination parameters are invalid.

## 3. Business Logic & Workflows

### 3.1. Accession Intake and the Deed-of-Gift Cycle

A `Registrar` opens the archive's legal intake by registering an **accession** with the donor's `donor_name`, `donor_contact`, the `accession_date` on which the materials were physically received (an ISO 8601 date), and `lot_appraised_value_cents`, the appraised value of the whole lot in cents, which may not be negative. At creation the accession enters `DRAFT` status and is assigned its `accession_number`: the four-digit year of its `created_at`, a hyphen, and the 1-based count of accessions created in that calendar year, zero-padded to three digits.

Submitting moves the accession `DRAFT → PENDING_DEED` and increments its `version` by 1. Before any deed has executed, the registrar may withdraw the accession — withdrawal is permitted from either `DRAFT` or `PENDING_DEED`, lands in the terminal `WITHDRAWN` state, and voids every deed still in `DRAFT` for that accession (each such deed becomes `VOIDED`). Once the accession is `ACCESSIONED`, the registrar may open an amendment cycle: amending moves the accession `ACCESSIONED → AMENDMENT_PENDING`, again incrementing its `version` by 1, and a newly executed deed closes the loop back to `ACCESSIONED`.

**Deeds of gift** are drafted under an accession while that accession is `PENDING_DEED`, `AMENDMENT_PENDING`, or `ACCESSIONED`; drafting under an accession in any other state is rejected with `ERR_INVALID_STATE`. Each deed is assigned a `deed_version` at creation — the 1-based count of deeds created for that accession up to and including this one. The deed captures four donor terms: `reproduction_restricted` (default false), which when true on the executed deed bars reproduction orders covering the accession's items; `publication_license_required` (default false), which bars personal-class reproduction orders; `embargo_until` (optional), which bars reproduction orders while it lies in the future; and `required_citation_text` (optional), the exact citation string that delivery acknowledgments must reproduce. A deed begins in `DRAFT`; the registrar may void it (`DRAFT → VOIDED`) at any time before execution.

Executing a deed is the pivotal legal act, and its checks fire in the global priority order. The deed itself must be `DRAFT`, else `ERR_INVALID_STATE`. The request must carry `expected_accession_version` matching the accession's current `version`, else the stale-version rejection of §2.7 applies with `ERR_STALE_VERSION`. And the accession must be `PENDING_DEED`, `AMENDMENT_PENDING`, or `ACCESSIONED`, else `ERR_ACCESSION_NOT_ACCESSIONED`. Executing over an already-`ACCESSIONED` accession is legitimate — it is how a replacement deed supersedes the current one — so the state gate deliberately admits `ACCESSIONED`, and the optimistic-concurrency check is the sole defense against a stale client view. On execution the deed becomes `EXECUTED`; the accession's `version` increments by 1; the previously `EXECUTED` deed for the accession, if any, becomes `SUPERSEDED`; the accession moves from `PENDING_DEED` to `ACCESSIONED` or from `AMENDMENT_PENDING` back to `ACCESSIONED`; and the accession's `current_deed_id` is updated to the newly executed deed. `current_deed_id` is null whenever the accession has no executed deed, and it is the pointer through which every reproduction and citation check in §3.7 resolves the governing donor terms.

### 3.2. Collections, Storage Zones, and Item Cataloging

Holdings are organized into **collections**, created by a `Registrar` with a `title`, a unique `collection_code` (a duplicate is rejected with `ERR_COLLECTION_CODE_EXISTS`), the `storage_zone_id` of the zone where the collection's physical items sit, and an optional `parent_collection_id` for fonds-and-series hierarchy. The parent must reference an existing collection and must not create a cycle — a collection may not be its own parent nor descend beneath one of its own descendants; violations are rejected with `ERR_COLLECTION_CYCLE`. A collection begins `ACTIVE`. Hierarchy maintenance is possible afterward by reparenting: the request body must carry a non-null `parent_collection_id` string, else `ERR_INVALID_REQUEST`; the new parent must exist (`ERR_NOT_FOUND`), must be neither the collection itself nor one of its descendants (`ERR_COLLECTION_CYCLE`), and the collection being moved must be `ACTIVE` (`ERR_INVALID_STATE`).

Two rollups track each collection continuously. `item_count` counts the collection's direct items whose status is not `DEACCESSIONED` — direct children only, never subcollection contents. `published_finding_aid_present` is true exactly when at least one finding aid for the collection has status `PUBLISHED`. Both are recomputed synchronously as items and finding aids change state.

An `Archivist` brings physical material under intellectual control by creating a stub **item**: the payload names the `accession_id` that brought the material in, the `collection_id` it will belong to, and a `title`. The accession must be `ACCESSIONED` (`ERR_ACCESSION_NOT_ACCESSIONED`) and the collection must be `ACTIVE` (`ERR_INVALID_STATE`). The new item enters `PENDING_CATALOG` and the collection's `item_count` increases by 1. At this stage the item's `description`, `condition_grade`, `appraised_value_cents`, and `format` are all null; they remain null until cataloged.

Cataloging completes the record: cataloging moves the item `PENDING_CATALOG → CATALOGED` and stores the `description`, the `condition_grade` (one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, `FRAGILE`), the item-level `appraised_value_cents` (non-negative), and the `format` (one of `MANUSCRIPT`, `PHOTOGRAPH`, `MAP`, `ARTIFACT`, `AUDIOVISUAL`, `BOUND_VOLUME`). Because the item was already counted at creation, cataloging leaves `item_count` unchanged.

Release to researchers is deliberately gated. Making an item available moves it `CATALOGED → AVAILABLE` only when three further conditions hold beyond the item's own state: the collection has a published finding aid (`ERR_FINDING_AID_NOT_PUBLISHED`), the item's accession is `ACCESSIONED` (`ERR_ACCESSION_NOT_ACCESSIONED`), and the collection's zone posture is `OPEN` (`ERR_ZONE_RESTRICTED`). An available item may be flagged for conservation (`AVAILABLE → FLAGGED_CONSERVATION`); treatment then moves it through `IN_TREATMENT` and back to `AVAILABLE` as §3.4 describes. Two further states arrive only through system cascades: `ZONE_HOLD`, entered and left automatically as the zone's posture shifts per §2.6, and the terminal `DEACCESSIONED`, reached from `PENDING_CATALOG`, `CATALOGED`, `AVAILABLE`, `FLAGGED_CONSERVATION`, or `ZONE_HOLD` when a deaccession proposal covering the item is finalized — an item in `IN_TREATMENT` cannot be deaccessioned at all, because approval and finalization are both blocked while any proposed item is in treatment.

### 3.3. Finding Aids and the Publication Gate

A **finding aid** is the collection's published description, and no item in the collection may become `AVAILABLE` until one exists in `PUBLISHED` status. An `Archivist` drafts a finding aid with the `collection_id` it describes, a `title`, a `summary`, and an optional `scope_note`; the collection must be `ACTIVE`, else `ERR_INVALID_STATE`. The aid begins in `DRAFT`.

Review follows a loop with a memory. Submitting for review moves the aid from `DRAFT` or `IN_REVISION` into `IN_REVIEW` and stamps `review_origin` with the state it came from. Publication moves `IN_REVIEW → PUBLISHED`: `published_revision_count` increases by 1, `published_at` records the logical timestamp of the publish, and the collection's `published_finding_aid_present` is recomputed — becoming true upon the first publication. Returning an aid under review routes it back to its stamped origin: `IN_REVIEW → DRAFT` when `review_origin` is `DRAFT`, and `IN_REVIEW → IN_REVISION` when `review_origin` is `IN_REVISION`; either way `review_origin` is cleared to null on return. A published aid may be reopened for revision (`PUBLISHED → IN_REVISION`), at which point the collection rollup is recomputed and drops to false when the reopened aid was the collection's only `PUBLISHED` one — which in turn blocks further make-available operations for that collection until publication is restored. Finally, when a collection is deaccessioned, each of its `PUBLISHED` finding aids becomes `RETIRED` and the rollup is recomputed once more. `published_at` is null until the aid's first publication.

### 3.4. Conservation Assessment and the Treatment Loop

When an item's condition worries the staff, an `Archivist` records a **conservation assessment** under the item. The creation payload carries the OCC field `expected_item_version` per §2.7 plus three professional judgments: `condition_grade_observed` (the same five-grade scale used at cataloging), `urgency_score` (an integer from 0 to 100 inclusive; anything outside that range is `ERR_INVALID_REQUEST`), and `treatment_estimate_hours` (a positive whole number of bench hours). The item must be `AVAILABLE` or `FLAGGED_CONSERVATION` — assessment creation is blocked while the item is `IN_TREATMENT`, surfacing as `ERR_INVALID_STATE`.

Creation has several immediate consequences beyond the new record. The item's `version` increments by 1. Any previous assessment for the item still in `DRAFT` or `APPROVED` status becomes `SUPERSEDED`. The system snapshots `open_request_count_snapshot` — the count of research requests referencing the item whose status is `SUBMITTED`, `IN_REVIEW`, or `APPROVED` — taken once at creation and never recomputed, so later request activity never revisits an assessment's demand term. The item's `current_assessment_id` moves to the new assessment. And `preliminary_priority_score` is computed: a weighted sum in which urgency carries half the weight, demand three-tenths, and value one-fifth. The demand term is the smaller of 100 and the snapshot count times 25 points per open request; the value term is the smaller of 100 and the item's `appraised_value_cents` divided by 1000 and rounded down to a whole number; the preliminary score combines the assessor's `urgency_score` as given with those two terms and rounds half up to 2 decimal places.

Approving an assessment (`DRAFT → APPROVED`) recomputes the score in its confirmed variant and publishes it to the item. The confirmed variant changes only the urgency term: when `condition_grade_observed` is `FRAGILE`, the effective urgency is the smaller of 100 and the raw `urgency_score` multiplied by 1.25 and rounded half up to a whole number; otherwise the urgency is used as given. The same creation-time snapshots feed every other term — approval never re-reads request counts. The result is stored as `confirmed_priority_score` (null until approval) and copied onto the item as its `conservation_priority_score`, with `current_assessment_id` confirmed at this assessment. One supersession nuance is pinned: when a newer assessment supersedes an `APPROVED` one, the item's `conservation_priority_score` keeps the older confirmed value — the newer assessment's preliminary score is not applied until that newer assessment is itself approved — while `current_assessment_id` moves to the newer record immediately. An item's `conservation_priority_score` is null whenever it has no `APPROVED` or `IN_TREATMENT` assessment.

Treatment is driven from the assessment. Beginning treatment requires the assessment to be `APPROVED` and its item to be `FLAGGED_CONSERVATION` (either violation is `ERR_INVALID_STATE`); it moves both into `IN_TREATMENT`. Completing treatment requires both to be `IN_TREATMENT`; it moves the assessment to `COMPLETED`, returns the item to `AVAILABLE`, sets the item's `condition_grade` to the request's `new_condition_grade`, and clears both `conservation_priority_score` and `current_assessment_id` on the item to null.

### 3.5. The Volunteer Digitization Program

A `VolunteerCoordinator` organizes digitization labor into **projects**, created with a `name`, an optional `description`, and an optional `max_hours_per_volunteer` — the lifetime per-volunteer hour cap for the project, defaulting to 40 hours, and required to be a non-negative integer when supplied. A project begins `PLANNED` with `volunteer_hours` an empty map, `hours_logged_total` zero, and `active_ticket_count` zero. Activation moves `PLANNED → ACTIVE`; closing moves `ACTIVE → CLOSED` and is refused with `ERR_ACTIVE_TICKETS_REMAIN` while the project's `active_ticket_count` — the number of its tickets in `CLAIMED`, `IN_CAPTURE`, or `QC_REVIEW` — is anything other than zero.

**Tickets** are queued under a project with a payload naming the `item_id` to digitize, supplied either as a plain string or as a reference object carrying an `id` string. The project must be `PLANNED` or `ACTIVE` (`ERR_INVALID_STATE`) — tickets may be queued before activation but not claimed — and the item must be `AVAILABLE` (`ERR_ITEM_NOT_AVAILABLE`). At creation the ticket's `priority_score` is computed and frozen for the ticket's whole life: a base of 50, plus 0.4 times the item's current `conservation_priority_score` (treated as zero when the item has none), plus 10 points per `APPROVED` research request referencing the item with the request contribution capped at three requests, the total rounded half up to 2 decimal places.

Claiming is a selector operation, not a pick-by-id operation: a `Volunteer` claims the next ticket under a project, and the system assigns from the claimable pool — the project's `QUEUED` tickets whose item is currently `AVAILABLE` — ranked by `priority_score` descending with ties broken by earliest `created_at` and any remaining ties broken by queueing order. The project must be `ACTIVE` (`ERR_INVALID_STATE`), and an empty pool is rejected with `ERR_NO_CLAIMABLE_TICKETS`. The selected ticket moves `QUEUED → CLAIMED`, its `claimed_by_user_id` records the caller's `X-User-ID`, and the project's `active_ticket_count` increases by 1.

Capture work belongs to the claimant. Beginning capture moves `CLAIMED → IN_CAPTURE`, and submitting for quality control moves `IN_CAPTURE → QC_REVIEW`; both are restricted to the volunteer whose id is stamped on the ticket, with anyone else rejected as `ERR_OWNERSHIP_MISMATCH`. Quality control is performed by a `VolunteerCoordinator` under segregation of duties: the reviewer's `X-User-ID` must differ from the ticket's `claimed_by_user_id`, else `ERR_QC_SELF_REVIEW`. A pass moves `QC_REVIEW → COMPLETE` and decrements the project's `active_ticket_count`; a fail loops the ticket `QC_REVIEW → IN_CAPTURE`, increments its `qc_fail_count`, and leaves `active_ticket_count` unchanged because the ticket remains active. A volunteer may also release a ticket they hold — from `CLAIMED` or `IN_CAPTURE` back to `QUEUED`, claimant only — which nulls `claimed_by_user_id` and decrements `active_ticket_count`, exactly compensating the claim.

Hours are logged against a held ticket. The ticket must be `CLAIMED` or `IN_CAPTURE` (`ERR_INVALID_STATE`), the caller must be the claimant (`ERR_OWNERSHIP_MISMATCH`), and the posted `hours` must be a positive multiple of 0.25 (`ERR_INVALID_REQUEST`). The project's per-volunteer ledger then governs: if the caller's accumulated hours on this project plus the posted hours would land strictly above `max_hours_per_volunteer`, the logging is rejected with `ERR_VOLUNTEER_HOUR_CAP_EXCEEDED`; landing exactly on the cap is allowed. On success the hours fold into three places at once — the ticket's `hours_logged`, the project's `hours_logged_total`, and the caller's entry in the project's `volunteer_hours` map.

A coordinator may cancel any non-terminal ticket — `QUEUED`, `CLAIMED`, `IN_CAPTURE`, or `QC_REVIEW` — moving it to `CANCELLED` and decrementing `active_ticket_count` when the cancelled ticket was in one of the three active states. The deaccession finalization of §3.8 cancels tickets through the same rule.

### 3.6. Researcher Registration, Research Requests, and the Reading Room

Public access begins at the reading-room desk, where `ReadingRoomStaff` register a **researcher** with `full_name`, a unique `email` (a duplicate is `ERR_DUPLICATE_EMAIL`), and an optional `affiliation`. The record begins `ACTIVE` with `no_show_strikes` at zero and `total_charged_cents` at zero — the latter being the running sum of `invoiced_fee_cents` across the researcher's paid and delivered reproduction orders, from which refunded orders contribute nothing (the refund flow of §3.7 unwinds the charge).

A registered researcher submits a **research request** carrying an `item_ids` array, a `topic`, and a `purpose` of `PERSONAL`, `ACADEMIC`, `COMMERCIAL`, or `PUBLICATION` — the purpose later drives reproduction-discount eligibility. The array must hold at least one and no more than ten entries; eleven or more is rejected with `ERR_TOO_MANY_ITEMS` and duplicate entries with `ERR_INVALID_REQUEST`, both before any item is looked up. The caller's researcher record is stamped onto the request as `researcher_id` from `X-User-ID`, and the caller must be `ACTIVE` — a suspended researcher is rejected with `ERR_RESEARCHER_SUSPENDED`. Every referenced item must exist (`ERR_NOT_FOUND`) and must be `AVAILABLE`; the first offending id in the order the array presents them is reported as `ERR_ITEM_NOT_AVAILABLE`. The request begins `SUBMITTED`.

Triage belongs to `ReadingRoomStaff`: beginning review moves `SUBMITTED → IN_REVIEW`; approval moves `IN_REVIEW → APPROVED`; denial moves `IN_REVIEW → DENIED` and stores the optional `decision_reason`. The researcher may cancel their own request while it is `SUBMITTED` or `IN_REVIEW` — the ownership check compares the request's `researcher_id` to the caller's `X-User-ID`, failing as `ERR_OWNERSHIP_MISMATCH` — landing in `CANCELLED`. A fourth, system-driven denial path exists during deaccession finalization and acts even on `APPROVED` requests; §3.8 covers it.

With an `APPROVED` request in hand, the researcher books a **reading-room appointment** naming the `research_request_id` it serves, a `room_code`, a `scheduled_date` in year-month-day form interpreted as UTC, a `start_time` and `end_time` in 24-hour hour-minute form, and optionally `seats` (defaulting to 1 and never less than 1). The two rooms differ in capacity: `MAIN` seats 8 and `MAP_ROOM` seats 4. The time interval is half-open — the start is inclusive and the end exclusive — so the start must strictly precede the end (`ERR_INVALID_REQUEST`), and an appointment that ends exactly when another begins does not overlap it. The booking cascade of checks: the request must be `APPROVED` (`ERR_REQUEST_NOT_APPROVED`) and owned by the caller (`ERR_REQUEST_OWNERSHIP_MISMATCH`); the caller must be `ACTIVE` (`ERR_RESEARCHER_SUSPENDED`); no item on the request may be `FRAGILE` — fragile material is never pulled to the reading room (`ERR_ITEM_TOO_FRAGILE`); every item on the request must be `AVAILABLE` (`ERR_ITEM_NOT_AVAILABLE`); and the appointment start — the `scheduled_date` at `start_time`, UTC — must lie strictly in the future of the logical clock (`ERR_APPOINTMENT_IN_PAST`).

Seat arithmetic then decides admission. Two appointments overlap when the first starts before the second ends and the second starts before the first ends. The seats already occupied are the sum of `seats` over appointments in the same room on the same date in `CONFIRMED` or `CHECKED_IN` status that overlap the candidate interval. The candidate is admitted only when occupied seats plus the requested `seats` come to no more than the room's capacity — a full house admits zero further seats, and overflow is rejected with `ERR_APPOINTMENT_CAPACITY_EXCEEDED`. Independently of times, a single item appearing on two distinct `CONFIRMED` appointments on the same `scheduled_date` is rejected with `ERR_ITEM_DOUBLE_BOOKED` at whole-day granularity. A successful booking lands in `CONFIRMED` with `researcher_id` stamped from the caller.

On the day, staff check the researcher in (`CONFIRMED → CHECKED_IN`) and complete the visit (`CHECKED_IN → COMPLETED`). When a confirmed slot passes unused, staff record a no-show: the appointment must be `CONFIRMED` (`ERR_INVALID_STATE` otherwise), and the logical clock must have reached or passed the appointment's end datetime — its `scheduled_date` at `end_time`, UTC — else `ERR_APPOINTMENT_NOT_ENDED`. The appointment becomes `NO_SHOW`, and the researcher's `no_show_strikes` is recomputed: the count of that researcher's `NO_SHOW` appointments whose `scheduled_date` falls on or after the date 180 days before the current logical date — the window boundary is inclusive, and dates are compared as UTC calendar dates. The count is evaluated against the current logical clock whenever the researcher record is read, so advancing the clock can lower the reported `no_show_strikes` without any new event. When a freshly recorded no-show brings the count to at least three and the researcher is still `ACTIVE`, the researcher becomes `SUSPENDED` and every one of their `CONFIRMED` appointments whose `scheduled_date` falls on or after the current logical date is cancelled; exactly three strikes suspends, two does not. The check is a level check evaluated on each no-show event, so reinstatement — staff moving a `SUSPENDED` researcher back to `ACTIVE` — deliberately does not erase strike history, and a later no-show recorded while the rolling count still stands at three or more suspends the researcher again.

Zone trouble reaches the reading room through `NEEDS_RESCHEDULE`. When a requested item enters `ZONE_HOLD`, each future-dated `CONFIRMED` appointment whose request references it moves to `NEEDS_RESCHEDULE`, and — per the pinned asymmetry of §2.6 — recovery of the zone does not restore it. The owning researcher reschedules by supplying a new `scheduled_date`, `start_time`, and `end_time`: the appointment returns to `CONFIRMED` with seats re-reserved for the new interval, but only after passing the same capacity, double-booking, and future-start validations as creation, plus a fresh check that every item on the underlying request is `AVAILABLE` at reschedule time (`ERR_ITEM_NOT_AVAILABLE`). The owner may instead cancel outright — cancellation is permitted from `CONFIRMED` or `NEEDS_RESCHEDULE` by the owning researcher (`ERR_OWNERSHIP_MISMATCH` otherwise) — which releases the reserved seats for the interval. System cascades that cancel appointments, such as the suspension cascade above and the deaccession cascade of §3.8, bypass the ownership check.

### 3.7. Reproduction Orders: Quoting, Licensing, Invoicing, and Delivery

A researcher holding an `APPROVED` request may place a **reproduction order** naming the `research_request_id`, an `item_ids` array, a `format`, a `page_estimate` (a positive integer), and optionally a `license_class` (default `PERSONAL`) and a `rush` flag (default false). The request must be `APPROVED` (`ERR_REQUEST_NOT_APPROVED`) and owned by the caller (`ERR_REQUEST_OWNERSHIP_MISMATCH`), and the caller must be `ACTIVE` (`ERR_RESEARCHER_SUSPENDED`). The `item_ids` array must be non-empty and every entry must be a member of the request's own `item_ids`; either failure is `ERR_ITEM_NOT_IN_REQUEST`. The format drives pricing: `SCAN_STANDARD` carries a multiplier of 1.0, `SCAN_HIGHRES` 1.8, and `PRINT_PHOTOGRAPH` 2.5. License classes carry flat fees: `PERSONAL` adds nothing, `NONPROFIT_PUBLICATION` adds 1500 cents, and `COMMERCIAL_PUBLICATION` adds 7500 cents.

Donor terms then gate the order, item by item. For each ordered item the system resolves the item's accession to its current `EXECUTED` deed through `current_deed_id` and applies three prohibitions: if that deed's `embargo_until` lies strictly after the current logical time, the order is rejected with `ERR_EMBARGO_ACTIVE`; if the deed's `reproduction_restricted` is true, with `ERR_DEED_REPRODUCTION_RESTRICTED`; and if the deed's `publication_license_required` is true while the order's `license_class` is `PERSONAL`, with `ERR_PUBLICATION_LICENSE_REQUIRED`. A `PERSONAL` order is the only class blocked by the license requirement; nonprofit and commercial publication classes satisfy it.

With the gates passed, the order is quoted and lands in `QUOTED` with `quoted_fee_cents` computed from `page_estimate`. The pricing algorithm runs identically at quote time and at invoice time, differing only in the page count fed to it. First, the image component prices pages in three tiers — the first 50 pages at 35 cents each, the next 150 pages at 25 cents each, and every page beyond 200 at 15 cents each — multiplies the tier cost by the format multiplier, multiplies again by 1.5 when `rush` is true, and rounds half up to whole cents. Second, the academic discount is decided: when the linked research request's `purpose` is `ACADEMIC` and the pre-discount image component is at least 5000 cents, the discount rate is 20 percent; otherwise it is zero. Third, the discounted amount is the image component multiplied by one minus the discount rate, rounded half up to whole cents. Fourth, the minimum order fee applies: the larger of 500 cents and the discounted amount. Fifth and last, the license flat fee for the order's `license_class` is added. The evaluation order is pinned — the discount tier keys on the pre-discount component, the minimum applies after discounting, and the license flat is added last — because keying the discount on the post-discount amount, or applying the minimum before the discount, yields different cents; both are forbidden. Rounding occurs at the first and third steps only.

The researcher accepts the quote (`QUOTED → APPROVED`; ownership-checked, `ERR_OWNERSHIP_MISMATCH`). Staff then invoice the order with the true `actual_pages` (a positive count), moving `APPROVED → INVOICED` and storing the recomputed fee as `invoiced_fee_cents`. Two fiscal gates guard invoicing. The requote gate: the invoiced fee may not exceed the quoted fee increased by ten percent and rounded down to whole cents; a breach is rejected with `ERR_REQUOTE_REQUIRED` and the order stays `APPROVED`. The quota gate: each researcher has an annual allowance of 500 reproduction pages per calendar year, measured in UTC, consumed by their orders in `INVOICED`, `PAID`, or `DELIVERED` status that were invoiced within the current calendar year — `REFUNDED` orders keep their debit and `QUOTED` or `APPROVED` orders consume nothing. If `actual_pages` strictly exceeds the remaining allowance the invoice is rejected with `ERR_REPRO_QUOTA_EXCEEDED`; landing exactly on the remaining allowance is permitted. A successful invoice debits the allowance by `actual_pages`.

Payment is exact-change only: the owning researcher pays — any other researcher is rejected with `ERR_OWNERSHIP_MISMATCH` — with `amount_cents` equal to `invoiced_fee_cents` to the cent, else `ERR_PAYMENT_AMOUNT_MISMATCH`, moving `INVOICED → PAID` and adding the invoiced amount to the researcher's `total_charged_cents`. Delivery then completes the order (`PAID → DELIVERED`) under a citation check evaluated against the deeds current at delivery time: the supplied `citation_acknowledgment_text` must be non-empty and, for every item on the order whose accession's current `EXECUTED` deed carries a non-null `required_citation_text`, must contain that exact text verbatim and case-sensitively, else `ERR_CITATION_MISMATCH`. Because the check reads the deed in force at delivery, an amended deed between payment and delivery changes what the acknowledgment must contain. Staff may instead refund a paid order (`PAID → REFUNDED`): the invoiced amount is subtracted back out of `total_charged_cents`, compensating the payment, but the annual page-quota debit is deliberately not released — this is pinned. Finally, orders still in `QUOTED` or `APPROVED` when a deaccession finalize removes their items are cancelled by the system; orders already `INVOICED`, `PAID`, or `DELIVERED` are untouched.

### 3.8. Deaccession Governance: Board Review, Cooling-Off, and Disposal

Deaccessioning removes material from the holdings under board governance. A `Registrar` drafts a **deaccession proposal** with an `item_ids` array (one or more entries; duplicates are `ERR_INVALID_REQUEST`), a `justification` text, and a `disposal_method` of `SALE`, `TRANSFER`, `DESTRUCTION`, or `RETURN_TO_DONOR`. Every referenced item must exist (`ERR_NOT_FOUND`) and must not already be `DEACCESSIONED` (`ERR_INVALID_STATE`). The registrar's `X-User-ID` is stamped as `proposed_by_user_id` and the proposal begins in `DRAFT`.

Internal routing moves the proposal `DRAFT → SUBMITTED` and then `SUBMITTED → BOARD_REVIEW`; the registrar may withdraw it from either `DRAFT` or `SUBMITTED` into `WITHDRAWN`. At the board, a `BoardOfficer` decides. Approval enforces segregation of duties — the approving officer's `X-User-ID` must differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and refuses to approve while any proposed item is `IN_TREATMENT` (`ERR_ITEMS_IN_TREATMENT`). Approval stamps `approved_by_user_id` and `approved_at` (the logical timestamp) and computes `finalize_not_before` as `approved_at` plus a 30-day cooling-off period. Rejection moves `BOARD_REVIEW → REJECTED`; deliberately, no segregation-of-duties check applies to rejection — the proposer's own board ally may reject, and this asymmetry is pinned.

Finalization is gated by the logical clock. A proposal sits in `APPROVED` until the clock reaches `finalize_not_before`, at which point the clock sweep of §2.5 moves it to `COOLED_OFF`. Calling finalize while the proposal is still `APPROVED` — that is, while the logical now has not yet reached `finalize_not_before` — fails with `ERR_COOLING_OFF_NOT_ELAPSED`. From `COOLED_OFF`, the registrar finalizes the proposal into the terminal `FINALIZED` state; finalization re-checks that no proposed item is `IN_TREATMENT` (`ERR_ITEMS_IN_TREATMENT`) and, for a `SALE` proposal, requires `hammer_prices` — an array pairing each proposed `item_id` with its `price_cents`, covering every proposed item exactly once, else `ERR_HAMMER_PRICE_MISSING`. For a sale, `proceeds_cents` is computed by rounding each line separately — each hammer price less the ten percent commission, rounded half up to whole cents per item — and then summing the rounded lines. The per-item-round-then-sum order is pinned: hammer prices of 999, 555, and 333 cents yield 1699 cents of proceeds under the pinned order, whereas summing first and rounding once would yield 1698; the latter is forbidden. For the other three disposal methods `hammer_prices` is not required — a supplied array is still shape-validated but is not stored on the proposal — and `proceeds_cents` stays null.

Finalization's cascade is the widest in the system, and every step completes before the response returns. **Link 1 — items:** every proposed item in `PENDING_CATALOG`, `CATALOGED`, `AVAILABLE`, `FLAGGED_CONSERVATION`, or `ZONE_HOLD` becomes `DEACCESSIONED`, and each affected collection's `item_count` decreases accordingly. **Link 2 — requests:** every research request in `SUBMITTED`, `IN_REVIEW`, or `APPROVED` whose `item_ids` intersect the deaccessioned set becomes `DENIED`, with `decision_reason` recorded as `AUTO_DEACCESSION`. **Link 3 — appointments:** every appointment in `CONFIRMED` or `NEEDS_RESCHEDULE` whose research request was denied in link 2 becomes `CANCELLED`. **Ticket fan-out:** every digitization ticket in `QUEUED`, `CLAIMED`, `IN_CAPTURE`, or `QC_REVIEW` whose item was deaccessioned becomes `CANCELLED`, with each project's `active_ticket_count` adjusted for the tickets that were active. **Order fan-out:** every reproduction order in `QUOTED` or `APPROVED` whose `item_ids` intersect the deaccessioned set becomes `CANCELLED`; orders in `INVOICED`, `PAID`, or `DELIVERED` are untouched — pinned. **Bubble-up:** a collection whose `item_count` reaches zero through link 1 deaccessions itself (`ACTIVE → DEACCESSIONED`), and each of its `PUBLISHED` finding aids becomes `RETIRED`, with `published_finding_aid_present` recomputed.

### 3.9. Oral History Recording and Release Management

The society's oral-history program books studio time, manages the interview workflow, and enforces the narrator's release rights as an independent dimension. An `Archivist` schedules a recording with the `collection_id` the interview accrues to, the `narrator_name`, the `interviewer_name`, a `recording_room_id` of `STUDIO_A` or `STUDIO_B`, and a `session_start` and `session_end`. The session bounds are closed, and the start must strictly precede the end (`ERR_INVALID_REQUEST`).

Each studio is a single-resource pool guarded by a mandatory 30-minute turnaround buffer, and its interval semantics deliberately differ from the reading room's. A new session conflicts with an existing non-cancelled session in the same room unless at least the full turnaround separates them — precisely, unless the new session's end plus 30 minutes falls at or before the existing session's start, or the existing session's end plus 30 minutes falls at or before the new session's start. A gap of exactly 30 minutes is permitted; a 29-minute gap is a conflict, rejected with `ERR_RECORDING_ROOM_CONFLICT`. Only sessions that have not been `CANCELLED` participate in the check. A successfully scheduled recording enters `SCHEDULED` with `release_status` `PENDING`.

The workflow dimension then walks the interview to publication: marking it recorded (`SCHEDULED → RECORDED`), submitting the transcript (`RECORDED → TRANSCRIBED`), sending it to review (`TRANSCRIBED → IN_REVIEW`), and — when review finds problems — returning it to transcription (`IN_REVIEW → TRANSCRIBED`), a loop that may repeat. Cancellation is available from `SCHEDULED`, `RECORDED`, `TRANSCRIBED`, or `IN_REVIEW` and lands in `CANCELLED`.

The release dimension moves independently of all the above. Recording the narrator's signed release requires `release_status` to be `PENDING` and the body's `signed_by_narrator_name` to equal the recording's `narrator_name` exactly — any difference, however small, is `ERR_NARRATOR_MISMATCH`. On signature the release becomes `SIGNED`, `release_signed_at` records the logical timestamp, and an optional `embargo_until` from the body is stored (it may be null). If the narrator refuses, the release becomes `DECLINED` from the same `PENDING` state. Publication (`IN_REVIEW → RELEASED`) joins the two dimensions: it requires the workflow state `IN_REVIEW`, a `release_status` of `SIGNED` (else `ERR_RELEASE_FORM_MISSING`), and any recorded `embargo_until` to have lapsed — an embargo lying strictly after the current logical time blocks publication with `ERR_ORAL_HISTORY_EMBARGOED`, while a null embargo or one exactly at the current time does not.

## 4. Endpoint Definitions

Operations that create new resources — including operations that append a new element to a resource's embedded collection, such as posting an environmental reading to a zone — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. All paths are rooted at the service base URL. Request payloads, validation order, and side effects for each operation are specified in §2 and §3; this table is an index, not the full contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock and sweep cooled-off proposals | SystemAdmin |
| POST | `/storage-zones` | Create a storage zone with environmental thresholds | Registrar, SystemAdmin |
| GET | `/storage-zones` | List storage zones (filter by `posture`) | Any |
| GET | `/storage-zones/{id}` | Get one storage zone with posture, streak, and readings | Any |
| POST | `/storage-zones/{id}/readings` | Append an environmental reading; replays posture and fires cascades | SystemAdmin, Archivist |
| POST | `/collections` | Create a collection, optionally under a parent | Registrar |
| GET | `/collections` | List collections | Any |
| GET | `/collections/{id}` | Get one collection | Any |
| PATCH | `/collections/{id}` | Reparent a collection (hierarchy maintenance) | Registrar |
| POST | `/accessions` | Register a new accession (donor lot intake) | Registrar |
| GET | `/accessions` | List accessions | Any |
| GET | `/accessions/{id}` | Get one accession | Any |
| POST | `/accessions/{id}/submit` | Submit accession: `DRAFT → PENDING_DEED` | Registrar |
| POST | `/accessions/{id}/amend` | Open a deed-amendment cycle: `ACCESSIONED → AMENDMENT_PENDING` | Registrar |
| POST | `/accessions/{id}/withdraw` | Withdraw an accession before any deed executes | Registrar |
| POST | `/accessions/{id}/deeds` | Draft a deed of gift for an accession | Registrar |
| GET | `/accessions/{id}/deeds` | List deeds of an accession | Any |
| POST | `/deeds/{id}/execute` | Execute a draft deed (OCC on the accession) | Registrar |
| POST | `/deeds/{id}/void` | Void a draft deed | Registrar |
| POST | `/items` | Create a stub item (`PENDING_CATALOG`) | Archivist |
| GET | `/items` | List items | Any |
| GET | `/items/{id}` | Get one item | Any |
| POST | `/items/{id}/catalog` | Complete cataloging: `PENDING_CATALOG → CATALOGED` | Archivist |
| POST | `/items/{id}/make-available` | Release a cataloged item for research (gated) | Archivist |
| POST | `/items/{id}/flag-conservation` | Flag an available item for conservation | Archivist |
| GET | `/items/{id}/research-requests` | List requests referencing this item | Any |
| GET | `/items/{id}/reproduction-orders` | List reproduction orders referencing this item | Any |
| GET | `/items/{id}/deaccession-proposals` | List deaccession proposals referencing this item | Any |
| POST | `/items/{id}/conservation-assessments` | Create a conservation assessment (OCC on the item) | Archivist |
| GET | `/items/{id}/conservation-assessments` | List assessments of an item | Any |
| POST | `/conservation-assessments/{id}/approve` | Approve a draft assessment; publish the confirmed score | Archivist |
| POST | `/conservation-assessments/{id}/begin-treatment` | Begin treatment on an approved assessment | Archivist |
| POST | `/conservation-assessments/{id}/complete-treatment` | Complete treatment; item returns to `AVAILABLE` | Archivist |
| POST | `/finding-aids` | Create a finding aid for a collection | Archivist |
| GET | `/finding-aids` | List finding aids | Any |
| GET | `/finding-aids/{id}` | Get one finding aid | Any |
| POST | `/finding-aids/{id}/submit-review` | Submit a finding aid for review | Archivist |
| POST | `/finding-aids/{id}/publish` | Publish a finding aid under review | Archivist |
| POST | `/finding-aids/{id}/return` | Return an aid under review to its origin state | Archivist |
| POST | `/finding-aids/{id}/open-revision` | Reopen a published aid for revision | Archivist |
| POST | `/volunteer-projects` | Create a volunteer processing project | VolunteerCoordinator |
| GET | `/volunteer-projects` | List volunteer projects | Any |
| GET | `/volunteer-projects/{id}` | Get one volunteer project | Any |
| POST | `/volunteer-projects/{id}/activate` | Activate a planned project | VolunteerCoordinator |
| POST | `/volunteer-projects/{id}/close` | Close an active project (requires zero active tickets) | VolunteerCoordinator |
| POST | `/volunteer-projects/{id}/tickets` | Queue a digitization ticket for an item | VolunteerCoordinator |
| GET | `/digitization-tickets` | List digitization tickets | Any |
| GET | `/digitization-tickets/{id}` | Get one digitization ticket | Any |
| POST | `/volunteer-projects/{id}/tickets/claim-next` | Claim the highest-priority claimable ticket | Volunteer |
| POST | `/digitization-tickets/{id}/begin-capture` | Begin capture on a claimed ticket (claimant only) | Volunteer |
| POST | `/digitization-tickets/{id}/submit-qc` | Submit captured work for quality control (claimant only) | Volunteer |
| POST | `/digitization-tickets/{id}/qc-pass` | Pass QC (reviewer must differ from claimant) | VolunteerCoordinator |
| POST | `/digitization-tickets/{id}/qc-fail` | Fail QC; ticket loops back to capture | VolunteerCoordinator |
| POST | `/digitization-tickets/{id}/release` | Release a claim back to the queue (claimant only) | Volunteer |
| POST | `/digitization-tickets/{id}/log-hours` | Log work hours on a held ticket | Volunteer |
| POST | `/digitization-tickets/{id}/cancel` | Cancel a non-terminal ticket | VolunteerCoordinator |
| POST | `/researchers` | Register a researcher | ReadingRoomStaff |
| GET | `/researchers` | List researchers | Any |
| GET | `/researchers/{id}` | Get one researcher | Any |
| POST | `/researchers/{id}/reinstate` | Reinstate a suspended researcher | ReadingRoomStaff |
| POST | `/research-requests` | Submit a research request over a set of items | Researcher |
| GET | `/research-requests` | List research requests | Any |
| GET | `/research-requests/{id}` | Get one research request | Any |
| POST | `/research-requests/{id}/begin-review` | Begin review of a submitted request | ReadingRoomStaff |
| POST | `/research-requests/{id}/approve` | Approve a request under review | ReadingRoomStaff |
| POST | `/research-requests/{id}/deny` | Deny a request under review | ReadingRoomStaff |
| POST | `/research-requests/{id}/cancel` | Researcher cancels own request | Researcher |
| POST | `/reading-room-appointments` | Book a reading-room slot against an approved request | Researcher |
| GET | `/reading-room-appointments` | List appointments | Any |
| GET | `/reading-room-appointments/{id}` | Get one appointment | Any |
| POST | `/reading-room-appointments/{id}/check-in` | Check in a confirmed appointment | ReadingRoomStaff |
| POST | `/reading-room-appointments/{id}/complete` | Complete a checked-in appointment | ReadingRoomStaff |
| POST | `/reading-room-appointments/{id}/record-no-show` | Record a no-show; may suspend the researcher | ReadingRoomStaff |
| POST | `/reading-room-appointments/{id}/cancel` | Researcher cancels own appointment; releases seats | Researcher |
| POST | `/reading-room-appointments/{id}/reschedule` | Reschedule a `NEEDS_RESCHEDULE` appointment | Researcher |
| POST | `/reproduction-orders` | Place a reproduction order (quote computed at creation) | Researcher |
| GET | `/reproduction-orders` | List reproduction orders | Any |
| GET | `/reproduction-orders/{id}` | Get one reproduction order | Any |
| POST | `/reproduction-orders/{id}/approve-quote` | Researcher accepts the quote | Researcher |
| POST | `/reproduction-orders/{id}/invoice` | Staff invoices with actual page count | ReadingRoomStaff |
| POST | `/reproduction-orders/{id}/pay` | Researcher pays the invoice (exact amount) | Researcher |
| POST | `/reproduction-orders/{id}/deliver` | Staff delivers; citation acknowledgment enforced | ReadingRoomStaff |
| POST | `/reproduction-orders/{id}/refund` | Staff refunds a paid order | ReadingRoomStaff |
| POST | `/deaccession-proposals` | Draft a deaccession proposal over a set of items | Registrar |
| GET | `/deaccession-proposals` | List deaccession proposals | Any |
| GET | `/deaccession-proposals/{id}` | Get one deaccession proposal | Any |
| POST | `/deaccession-proposals/{id}/submit` | Submit a draft proposal | Registrar |
| POST | `/deaccession-proposals/{id}/send-to-board` | Send a submitted proposal to the board | Registrar |
| POST | `/deaccession-proposals/{id}/approve` | Board approves; starts the 30-day cooling-off | BoardOfficer |
| POST | `/deaccession-proposals/{id}/reject` | Board rejects (no segregation-of-duties restriction) | BoardOfficer |
| POST | `/deaccession-proposals/{id}/withdraw` | Withdraw a draft or submitted proposal | Registrar |
| POST | `/deaccession-proposals/{id}/finalize` | Finalize a cooled-off proposal; fires the full cascade | Registrar |
| POST | `/oral-histories` | Schedule an oral-history recording session | Archivist |
| GET | `/oral-histories` | List oral histories | Any |
| GET | `/oral-histories/{id}` | Get one oral history | Any |
| POST | `/oral-histories/{id}/mark-recorded` | Mark a scheduled session as recorded | Archivist |
| POST | `/oral-histories/{id}/submit-transcript` | Submit the transcript | Archivist |
| POST | `/oral-histories/{id}/send-to-review` | Send the transcript to review | Archivist |
| POST | `/oral-histories/{id}/return-to-transcription` | Return from review to transcription | Archivist |
| POST | `/oral-histories/{id}/release-forms/sign` | Record the narrator's signed release | Archivist |
| POST | `/oral-histories/{id}/release-forms/decline` | Record the narrator's refusal | Archivist |
| POST | `/oral-histories/{id}/publish-release` | Publish a reviewed recording with signed release | Archivist |
| POST | `/oral-histories/{id}/cancel` | Cancel a non-terminal recording | Archivist |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACCESSION_NOT_ACCESSIONED` | 409 Conflict |
| `ERR_FINDING_AID_NOT_PUBLISHED` | 409 Conflict |
| `ERR_ZONE_RESTRICTED` | 409 Conflict |
| `ERR_ITEM_NOT_AVAILABLE` | 409 Conflict |
| `ERR_REQUEST_NOT_APPROVED` | 409 Conflict |
| `ERR_RESEARCHER_SUSPENDED` | 409 Conflict |
| `ERR_ITEM_TOO_FRAGILE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_QC_SELF_REVIEW` | 409 Conflict |
| `ERR_EMBARGO_ACTIVE` | 409 Conflict |
| `ERR_DEED_REPRODUCTION_RESTRICTED` | 409 Conflict |
| `ERR_PUBLICATION_LICENSE_REQUIRED` | 409 Conflict |
| `ERR_RELEASE_FORM_MISSING` | 409 Conflict |
| `ERR_ORAL_HISTORY_EMBARGOED` | 409 Conflict |
| `ERR_CITATION_MISMATCH` | 422 Unprocessable Content |
| `ERR_APPOINTMENT_IN_PAST` | 422 Unprocessable Content |
| `ERR_APPOINTMENT_NOT_ENDED` | 409 Conflict |
| `ERR_COOLING_OFF_NOT_ELAPSED` | 409 Conflict |
| `ERR_APPOINTMENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ITEM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RECORDING_ROOM_CONFLICT` | 409 Conflict |
| `ERR_COLLECTION_CODE_EXISTS` | 409 Conflict |
| `ERR_ZONE_CODE_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_COLLECTION_CYCLE` | 422 Unprocessable Content |
| `ERR_TOO_MANY_ITEMS` | 422 Unprocessable Content |
| `ERR_VOLUNTEER_HOUR_CAP_EXCEEDED` | 409 Conflict |
| `ERR_NO_CLAIMABLE_TICKETS` | 409 Conflict |
| `ERR_ACTIVE_TICKETS_REMAIN` | 409 Conflict |
| `ERR_ITEMS_IN_TREATMENT` | 409 Conflict |
| `ERR_NARRATOR_MISMATCH` | 400 Bad Request |
| `ERR_REQUEST_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_ITEM_NOT_IN_REQUEST` | 422 Unprocessable Content |
| `ERR_REPRO_QUOTA_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_REQUOTE_REQUIRED` | 409 Conflict |
| `ERR_HAMMER_PRICE_MISSING` | 422 Unprocessable Content |

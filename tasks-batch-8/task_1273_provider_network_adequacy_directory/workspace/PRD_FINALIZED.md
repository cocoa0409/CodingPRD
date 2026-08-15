# Provider Network Adequacy API — Product Requirements Document

## 1. Introduction

Health plans operating under state network-adequacy regulation face a recurring problem: the directory their members use to find care drifts out of date between quarterly measurement snapshots, and the network behind it drifts out of compliance with the time, distance, and capacity standards that regulators enforce. Phone numbers change. Panels close. Providers stop accepting new patients but stay listed. A member calls three numbers from the directory, gets three dead ends, and files a complaint — at which point the plan discovers the underlying provider has been out of contract for months.

This document specifies a Provider Network Adequacy and Directory Accuracy API that treats adequacy measurement, directory attestation, appointment-availability probing, deficiency remediation, and penalty exposure as one coupled system rather than five disconnected ones. The same `Provider` row that anchors a network-adequacy ratio also anchors the `DirectoryListing` a member sees, the `AttestationRecord` the plan uses to confirm the listing's data, the `AvailabilityProbe` that tests whether the listed office actually answers the phone, and the `DeficiencyRecord` that accrues penalty when too few providers serve too many members. A single suspension of a provider cascades through every one of those surfaces; a single listing removal cancels attestation work mid-flight; a single confirmed member complaint spawns a correction whose verification closes the complaint and clears the listing's data-error flag.

The system serves four operational roles with distinct duties. A `NetworkManager` operates the network day-to-day: loading providers, maintaining standards, publishing listings, running attestation cycles, scheduling probes, and finalizing evaluation periods. A `ComplianceOfficer` adjudicates member complaints and verifies directory corrections — never their own. A `Regulator` reviews access-plan (exception) requests and reads penalty exposure. A `ProviderRep` responds to attestation outreach on behalf of the provider they represent, and a `Member` files complaints from the field. The rest of this document specifies the global contracts (§2), the business workflows (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The `X-User-Role` value must be exactly one of `NetworkManager`, `ComplianceOfficer`, `Regulator`, `ProviderRep`, or `Member`. A request missing either header, or carrying an unrecognized role string, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed on the endpoint's authorized-role set is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `NetworkManager`, `ComplianceOfficer`, or `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` on `DirectoryCorrection` when a `NetworkManager` files a manual correction, or as `verified_by_user_id` when a `ComplianceOfficer` verifies one) but does not compare it to any entity's `id`. When `X-User-Role` is `ProviderRep`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; the same ownership rule applies to resources that reference a `Member`. A mismatch on either entity-backed role yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. List results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in this system carries `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits), and `updated_at` (same format, refreshed on every mutation). Every entity except `RegionSpecialtyResult` also carries `version`, an integer that increments by 1 on every mutation — including cascade-driven mutations where the entity was not the request's primary target. `RegionSpecialtyResult` rows are immutable snapshots: they carry `id` and `created_at` only; both `updated_at` and `version` are absent.

The system maintains a logical clock, distinct from wall-clock time, initialized to exactly `2026-05-01T00:00:00Z` at startup and advanced only by an administrative clock-set capability whose input is `to_iso8601`. The clock never falls back to wall-clock time. Business rules that gate on dates — contract effectuation, cycle advance windows, complaint filing windows, probe requested dates, excuse-window starts — all read this logical clock, never the host's system time.

### 2.5. Precision, Rounding, and Integer Arithmetic

Monetary amounts are stored and exposed as integer cents. Per-deficiency penalty accruals are rounded half-up to integer cents per accrual event before any summation; summing raw fractional cents and rounding once at the end is forbidden because the two orders yield different totals. Ratios and wait-time means are rounded half-up to 2 decimal places. The attestation response rate is rounded half-up to 4 decimal places, with the 0/0 case defined as null. The time-and-distance compliance gate is evaluated in exact integer arithmetic — ten times the compliant-location count compared against nine times the counted-location count — so that the 90% boundary is inclusive with no floating-point tolerance.

### 2.6. Optimistic Concurrency Control

Four write endpoints guard against stale client state via an explicit expected-version field. A request to update a `NetworkStandard` must carry `expected_standard_version` equal to that standard's current `version`; a mismatch is rejected with `ERR_STALE_STANDARD_VERSION` (HTTP 412). A request to patch a `PracticeLocation` must carry `expected_location_version`; mismatch yields `ERR_STALE_LOCATION_VERSION` (HTTP 412). A request to patch a `DirectoryListing` (any `to_status` transition) must carry `expected_listing_version`; mismatch yields `ERR_STALE_LISTING_VERSION` (HTTP 412). A request to create an `AccessPlanRequest` on a `DeficiencyRecord` must carry `expected_deficiency_version` matching the deficiency's current `version`; mismatch yields `ERR_STALE_DEFICIENCY_VERSION` (HTTP 412). The version check runs before any business logic on these four endpoints, so a stale write is rejected before its state-machine preconditions are even evaluated. Endpoints not named above do not accept a version field.

### 2.7. Validation Ordering Across the Request Pipeline

Every request passes through a fixed pipeline of validation categories, evaluated in this order. Authentication and role checks come first: the headers are present and the role is recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then the role is permitted on this endpoint (`ERR_FORBIDDEN`), then entity-backed ownership is verified where applicable (`ERR_NOT_RESOURCE_OWNER`). On the four OCC-guarded writes the stale-version check runs immediately after ownership and before any business logic. Next, path and body-referenced identifiers are resolved left-to-right (`ERR_REGION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ATTESTATION_RECORD_NOT_FOUND`, `ERR_PROBE_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND`). After all referents exist, state-machine preconditions evaluate (the various `ERR_*_INVALID_*`, `ERR_*_NOT_*` 409 codes). Segregation-of-duties on correction verification (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) runs next, then temporal and window guards (`ERR_CYCLE_NOT_YET_ADVANCEABLE`, `ERR_COMPLAINT_WINDOW_EXPIRED`, `ERR_PROBE_DATE_ORDER`, `ERR_EXCUSE_WINDOW_INVALID`), then cross-entity referential coherence (`ERR_LOCATION_PROVIDER_MISMATCH`, `ERR_LISTING_NOT_IN_MEMBER_REGION`, `ERR_CORRECTION_LISTING_MISMATCH`, `ERR_SPECIALTY_STANDARD_MISSING`), then uniqueness and overlap constraints (`ERR_NPI_DUPLICATE`, `ERR_REGION_DUPLICATE`, `ERR_MEMBER_REF_DUPLICATE`, `ERR_STANDARD_DUPLICATE`, `ERR_LISTING_ALREADY_LISTED`, `ERR_CYCLE_WINDOW_OVERLAP`, `ERR_CYCLE_ALREADY_ACTIVE`, `ERR_EXCUSE_WINDOW_OVERLAP`, `ERR_EVALUATION_ALREADY_OPEN`). There is no fiscal gate — penalty exposure is computed but never blocks an operation. `ERR_INVALID_REQUEST` (HTTP 400) covers malformed payloads, missing required fields, invalid enum values, and bad create-time date ordering anywhere in the pipeline.

### 2.8. The Coupled Spine: How One Mutation Fans Out

The system's defining structural property is that `Provider`, `PracticeLocation`, `DirectoryListing`, `AttestationCycle`, `AttestationRecord`, `AvailabilityProbe`, `AdequacyEvaluation`, `DeficiencyRecord`, `MemberComplaint`, and `DirectoryCorrection` all share a common spine — the listing and its location — so a single mutation routinely fans out through three or more entities. Suspending a provider suppresses every `LISTED` listing of that provider and bumps each listing's `version`. Terminating a provider removes all of its listings, cancels every `PENDING` attestation record attached to those listings, and forces the owning cycle's counters to recompute. Recording a probe outcome recomputes the listing's consecutive-FAIL count and may push the listing into `UNDER_REVIEW`, which removes it from the counted set used by the next adequacy finalize. Approving an access-plan request flips the deficiency to `EXCUSED`, reverses its outstanding penalty, and decrements the evaluation's `total_penalty_cents` by the same amount. Implementers should expect every write to require multi-entity bookkeeping; the cascade rules are stated in §3 alongside the workflows that trigger them.

## 3. Business Logic & Workflows

### 3.1. Bootstrapping the Network: Regions, Standards, Providers, Locations

A `NetworkManager` begins by registering the service regions the plan operates in. Each region carries a unique `county_fips`, a display `name`, a `geo_class` of `URBAN`, `SUBURBAN`, or `RURAL` (which selects which `NetworkStandard` row applies to listings in this region), and an `enrolled_member_count` snapshot that is the numerator source for the adequacy ratio. A duplicate `county_fips` is rejected with `ERR_REGION_DUPLICATE`.

Adequacy standards are registered per `(specialty, geo_class)` pair. The `specialty` is one of `PRIMARY_CARE`, `CARDIOLOGY`, `DERMATOLOGY`, or `BEHAVIORAL_HEALTH`; the `geo_class` is one of `URBAN`, `SUBURBAN`, `RURAL`. A standard carries `max_members_per_provider` (the adequacy ratio ceiling), `max_travel_minutes` and `max_travel_miles` (per-location time and distance standards, both inclusive upper bounds), and `max_wait_days_routine` and `max_wait_days_urgent` (the appointment-availability ceilings for `ROUTINE` and `URGENT` probes respectively, also inclusive). A duplicate `(specialty, geo_class)` pair is rejected with `ERR_STANDARD_DUPLICATE`. Updating an existing standard's thresholds is an OCC-guarded write: the caller passes `expected_standard_version` plus any subset of `max_members_per_provider`, `max_travel_minutes`, `max_travel_miles`, `max_wait_days_routine`, and `max_wait_days_urgent`; on success the standard's `version` increments by 1.

Provider onboarding is gated on the logical clock. A `NetworkManager` loads a new provider with `npi` (unique, else `ERR_NPI_DUPLICATE`), `legal_name`, `specialty`, and `contract_effective_date`. If the current logical clock date is at or past `contract_effective_date`, the new provider's `status` is immediately `EFFECTIVE`; otherwise the provider is held at `PENDING_LOAD` until a future clock advance sweeps it forward. The sweep runs as a side effect of the administrative clock-set capability: any provider in `PENDING_LOAD` whose `contract_effective_date` is at or before the new clock date transitions to `EFFECTIVE`, and each effectuated provider's `version` increments by 1. The clock-set call returns the new `current_utc` and the list of `effectuated_provider_ids`.

Practice locations sit at the join of provider and region. Creating one requires `provider_id`, `region_id`, `address_line`, `avg_travel_minutes`, and `avg_travel_miles`; `panel_status` defaults to `OPEN` but may be set to `CLOSED` at create time. The two travel-survey values feed the time-and-distance compliance check at evaluation finalize. Patching a location is OCC-guarded via `expected_location_version` and may update `panel_status`, `avg_travel_minutes`, `avg_travel_miles`, or `address_line`.

### 3.2. Publishing and Maintaining the Directory

A `DirectoryListing` is the public-facing representation of a provider at a location for a specialty. Creating one requires `provider_id`, `location_id`, `specialty`, `display_name`, `phone`, and `accepts_new_patients`; `office_hours_note` is optional. The listing is born in `DRAFT`. The listed `specialty` is independent of the provider's own `specialty` — a multi-specialty group may publish distinct listings per specialty at the same address.

Publishing a listing (transitioning `DRAFT` → `LISTED`) enforces four checks in order. First, the provider must be `EFFECTIVE` (`ERR_PROVIDER_NOT_EFFECTIVE`) — this check runs before the referential checks so a not-yet-effective provider surfaces its own error rather than being masked by a location mismatch. Second, the location's owning provider must equal the listing's `provider_id` (`ERR_LOCATION_PROVIDER_MISMATCH`). Third, a `NetworkStandard` must exist for `(listing.specialty, location.region.geo_class)` (`ERR_SPECIALTY_STANDARD_MISSING`) — without a standard there is no adequacy ceiling to measure this listing against. Fourth, no other listing may already be `LISTED` for the same `(location_id, specialty)` (`ERR_LISTING_ALREADY_LISTED`). On success the listing's `listed_at` is stamped with the current clock and `version` increments by 1.

From `LISTED`, a listing may be manually suppressed (transition to `SUPPRESSED` with `suppress_reason` = `MANUAL`) or may transition to `UNDER_REVIEW` automatically when the ghost-strike rule fires (see §3.5). From `UNDER_REVIEW`, a `NetworkManager` may either clear the review back to `LISTED` (which resets `ghost_strike_count` to 0) or confirm the ghost and transition to `SUPPRESSED` with `suppress_reason` = `GHOST_CONFIRMED`. Reinstatement from `SUPPRESSED` back to `LISTED` is reason-dependent. A listing suppressed for `MANUAL` reasons may be reinstated directly. A listing suppressed because its provider was suspended (`suppress_reason` = `PROVIDER_SUSPENDED`) is not manually reinstatable — attempting it is rejected with `ERR_LISTING_INVALID_TRANSITION`; restoration happens only through the provider-reinstate cascade (§3.3). A listing suppressed for `ATTESTATION_FAILURE` requires, before reinstatement, the existence of an `AttestationRecord` for this listing in `ATTESTED` or `CORRECTION_REQUESTED` status whose `responded_at` is strictly later than the listing's `suppressed_at`; otherwise the reinstate is rejected with `ERR_LISTING_ATTESTATION_UNRESOLVED`. A listing suppressed for `GHOST_CONFIRMED` requires an `AvailabilityProbe` for this listing with `result` = `PASS` and `recorded_at` strictly later than `suppressed_at`; otherwise the reinstate is rejected with `ERR_LISTING_GHOST_UNRESOLVED`. Every successful reinstate clears `suppress_reason` back to `NONE`.

A listing may be removed from any non-terminal status — `DRAFT`, `LISTED`, `UNDER_REVIEW`, or `SUPPRESSED`. Removal cascades: any `PENDING` `AttestationRecord` for this listing in a non-`CLOSED` cycle transitions to `CANCELLED` (its `version` incrementing by 1), and the owning cycle's counters recompute. Removal is terminal; a `REMOVED` listing may not be republished, may not receive new complaints or corrections, and may not have new probes scheduled against it (any such attempt yields `ERR_LISTING_REMOVED`).

All listing status patches — `to_status` of `LISTED`, `SUPPRESSED`, or `REMOVED`, with an optional `suppress_reason` — are OCC-guarded via `expected_listing_version`. A patch whose expected version does not match the listing's current `version` is rejected with `ERR_STALE_LISTING_VERSION` before any state-machine precondition is evaluated. This is the serialization point between, say, a correction verify that just bumped the listing's `version` and a `NetworkManager` trying to reinstate the listing from a stale read.

### 3.3. Provider Lifecycle: Suspend, Reinstate, Terminate

Once `EFFECTIVE`, a provider may be suspended and later reinstated, or terminated outright.

Suspension (`EFFECTIVE` → `SUSPENDED`) cascades into the directory: every `DirectoryListing` of this provider currently in `LISTED` status transitions to `SUPPRESSED` with `suppress_reason` = `PROVIDER_SUSPENDED`, `suppressed_at` stamped to the current clock, and `version` incremented by 1. Listings already in `DRAFT`, `UNDER_REVIEW`, `SUPPRESSED`, or `REMOVED` are untouched. Reinstatement (`SUSPENDED` → `EFFECTIVE`) runs the compensating cascade: every listing of this provider in `SUPPRESSED` with `suppress_reason` = `PROVIDER_SUSPENDED` transitions back to `LISTED`, `suppress_reason` cleared to `NONE`, `version` incremented by 1. This restores exactly the set the suspend cascade suppressed — listings suppressed for other reasons (`MANUAL`, `ATTESTATION_FAILURE`, `GHOST_CONFIRMED`) are not touched, and listings that transitioned out of `LISTED` between the suspend and the reinstate are not resurrected. The invariant that results is that for every `(region, specialty)` pair, the count of `LISTED` listings is unchanged across a suspend-then-reinstate pair. An attempt to suspend from any status other than `EFFECTIVE`, or to reinstate from any status other than `SUSPENDED`, is rejected with `ERR_PROVIDER_INVALID_TRANSITION`.

Termination is reachable from `PENDING_LOAD`, `EFFECTIVE`, or `SUSPENDED`. It stamps `terminated_at` to the current clock and runs a three-link cascade. Link 1: every listing of this provider in `DRAFT`, `LISTED`, `UNDER_REVIEW`, or `SUPPRESSED` transitions to `REMOVED`, `version` incremented. Link 2: every `AttestationRecord` whose listing was just removed and whose status is `PENDING` transitions to `CANCELLED`, `version` incremented. Link 3: each owning `AttestationCycle`'s counters (`total_records`, `pending_count`, `responded_count`, `non_responsive_count`) recompute over records whose status is not `CANCELLED`. Termination from `TERMINATED` itself is rejected with `ERR_PROVIDER_INVALID_TRANSITION`.

### 3.4. Attestation Cycles: Scheduled Outreach and the Non-Response Sweep

Attestation is organized into cycles. A `NetworkManager` schedules a cycle by supplying `cycle_label` (unique), `open_date`, `due_date`, and `outreach_close_date`. The three dates must satisfy the strict ordering `open_date` before `due_date` before `outreach_close_date`; bad ordering is rejected with `ERR_INVALID_REQUEST`. The cycle's window from `open_date` (inclusive) to `outreach_close_date` (exclusive) must not overlap any existing cycle's window — adjacency is allowed, so one cycle's `outreach_close_date` may equal another's `open_date` — otherwise the create is rejected with `ERR_CYCLE_WINDOW_OVERLAP`. The cycle is born in `SCHEDULED`.

Advancing the cycle is a three-step state machine driven by a `NetworkManager` and gated on the logical clock. `SCHEDULED` → `OPEN` requires the clock date to be at or past `open_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE` — the temporal check runs before the singleton check so a too-early advance surfaces its own error) and no other cycle currently in `OPEN` or `OUTREACH` (else `ERR_CYCLE_ALREADY_ACTIVE`). On this transition the system bulk-creates one `AttestationRecord` in `PENDING` status with `outreach_attempts` = 0 for every `DirectoryListing` that is `LISTED` at this instant, and the cycle's counters initialize. `OPEN` → `OUTREACH` requires the clock date at or past `due_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE`); on this transition every record still in `PENDING` has its `outreach_attempts` incremented by 1 and its `version` bumped, and the cycle counters recompute. `OUTREACH` → `CLOSED` requires the clock date at or past `outreach_close_date` (else `ERR_CYCLE_NOT_YET_ADVANCEABLE`); on this transition every record still in `PENDING` flips to `NON_RESPONSIVE` (link 1), each such record's listing — if still `LISTED` — transitions to `SUPPRESSED` with `suppress_reason` = `ATTESTATION_FAILURE` and `suppressed_at` stamped (link 2), and the cycle counters recompute so that `pending_count` falls to 0 while `non_responsive_count` rises (link 3). Advancing from any other state, or advancing a `CLOSED` cycle, is rejected with `ERR_CYCLE_INVALID_STATE`.

The cycle's computed counters are `total_records` (records of this cycle not in `CANCELLED`), `pending_count`, `responded_count` (records in `ATTESTED` plus records in `CORRECTION_REQUESTED`), and `non_responsive_count`. From these the response rate is derived on read in two variants: the strict rate divides the count of `ATTESTED` records by `total_records`, and the lenient rate divides the count of `ATTESTED` plus `CORRECTION_REQUESTED` records by `total_records`. Both are rounded half-up to 4 decimal places; when `total_records` is zero the rate is null.

### 3.5. Provider Responses and the Ghost-Network Detection Loop

A `ProviderRep` responds to attestation outreach on behalf of the provider they represent — the call's `X-User-ID` must equal the `id` of the `Provider` that owns the record's listing, else `ERR_NOT_RESOURCE_OWNER`. The response payload carries `data_accurate` and, when `data_accurate` is false, a `corrected_payload` describing the corrections needed.

A record in `PENDING` may be responded to while its cycle is `OPEN` or `OUTREACH`. A record in `NON_RESPONSIVE` may be responded to late, after its cycle has `CLOSED`. Any other combination — responding twice, responding after the record has already been cancelled, responding while the cycle is still `SCHEDULED` — is rejected with `ERR_RECORD_NOT_RESPONDABLE`. When `data_accurate` is true, the record transitions to `ATTESTED` and `responded_at` is stamped; cycle counters recompute. When `data_accurate` is false, `corrected_payload` must be present and non-empty (else `ERR_INVALID_REQUEST`); the record transitions to `CORRECTION_REQUESTED`, `responded_at` is stamped, and the system spawns a `DirectoryCorrection` on the record's listing with `changes` taken from `corrected_payload`, `complaint_id` null, `submitted_by_user_id` set to the responding `ProviderRep`'s `X-User-ID`, status `SUBMITTED`, and `sla_due_at` set 72 hours after the spawn timestamp. A late response from `NON_RESPONSIVE` follows the same shape: `ATTESTED` on accurate, `CORRECTION_REQUESTED` (with the same correction spawn) on corrected, and the cycle's `non_responsive_count` decreases while `responded_count` increases.

Ghost-network detection runs on appointment-availability probes. A `NetworkManager` schedules a probe against a listing that must currently be `LISTED` (else `ERR_LISTING_NOT_LISTED`), supplying `probe_type` (`ROUTINE` or `URGENT`) and `requested_date`. The `requested_date` must not be after the current clock date; otherwise the create is rejected with `ERR_PROBE_DATE_ORDER`. The probe is born in `SCHEDULED`. Recording the outcome transitions the probe to `RECORDED` (terminal) and requires `outcome`, one of `KEPT`, `UNREACHABLE`, or `NO_APPOINTMENT_OFFERED`. When `outcome` is `KEPT`, `offered_appointment_date` is required and must be on or after `requested_date` (else `ERR_PROBE_DATE_ORDER`); when `outcome` is `UNREACHABLE` or `NO_APPOINTMENT_OFFERED`, `offered_appointment_date` stays null. Recording against a probe already in `RECORDED` is rejected with `ERR_PROBE_INVALID_STATE`.

On record, three computed fields land on the probe. `days_to_appointment` is the whole-day difference between `offered_appointment_date` and `requested_date`, present only when the outcome is `KEPT`. `result` is `PASS` when the outcome is `KEPT` and `days_to_appointment` is at or below the applicable standard's wait ceiling — `max_wait_days_routine` for a `ROUTINE` probe, `max_wait_days_urgent` for an `URGENT` probe — and `FAIL` otherwise; the boundary is inclusive, so a wait equal to the ceiling passes. The applicable standard is the `NetworkStandard` for the pair of the listing's `specialty` and the listing's location's region's `geo_class`. `recorded_at` is stamped with the current clock.

Recording also recomputes the listing's `ghost_strike_count`. The recomputation replays this listing's `RECORDED` probes in chronological order by `recorded_at` ascending (ties broken by `created_at` ascending), walking a running count that resets to 0 on every `PASS` and increments by 1 on every `FAIL`; the value after the newest probe is the new `ghost_strike_count`. When the recomputed count reaches 3 and the listing is currently `LISTED`, the listing automatically transitions to `UNDER_REVIEW` and its `version` increments by 1 — this is the system's way of pulling the listing out of the counted adequacy set while a human decides whether the ghost is confirmed. The threshold boundary is inclusive: the third consecutive `FAIL` transitions. A subsequent `PASS` resets the count to 0, as does the `UNDER_REVIEW` → `LISTED` clear-review transition.

### 3.6. Member Complaints and the Directory Correction Pipeline

A `Member` files a complaint against a listing that serves their region. The call's `X-User-ID` must be the `id` of an existing `Member` — it becomes the complaint's `member_id` — and that member must be `ENROLLED` (else `ERR_MEMBER_NOT_ENROLLED`). The complaint carries `listing_id`, `error_type` (one of `WRONG_PHONE`, `WRONG_ADDRESS`, `NOT_ACCEPTING`, `NO_APPOINTMENT`, `OTHER`), `error_observed_date`, and free-text `description`. The listing must not be `REMOVED` (else `ERR_LISTING_REMOVED`), and the listing's location's region must equal the member's `region_id` (else `ERR_LISTING_NOT_IN_MEMBER_REGION`). The filing window is 90 days: the difference between the filing date and `error_observed_date` must not exceed 90 days, and `error_observed_date` must not be in the future; violation yields `ERR_COMPLAINT_WINDOW_EXPIRED`. On success the complaint is born in `OPEN` with `filed_at` stamped to the current clock.

A `ComplianceOfficer` adjudicates an `OPEN` complaint (else `ERR_COMPLAINT_NOT_OPEN`). The `outcome` is either `CONFIRMED_ERROR` or `UNFOUNDED`. An `UNFOUNDED` outcome simply transitions the complaint to `UNFOUNDED` (terminal) and increments `version`. A `CONFIRMED_ERROR` outcome requires `correction_changes` to be present and non-empty (else `ERR_INVALID_REQUEST`); it stamps `confirmed_at`, increments `version`, spawns a `DirectoryCorrection` on the complaint's listing with `complaint_id` set to the complaint, `changes` taken from `correction_changes`, `submitted_by_user_id` set to the literal string `system:adjudication`, status `SUBMITTED`, and `sla_due_at` 72 hours out, and sets the listing's `has_confirmed_data_error` to true (bumping the listing's `version`). The `notes` field is optional on adjudication and recorded on the complaint.

A `DirectoryCorrection` may also be filed manually by a `NetworkManager`, with `listing_id`, `changes`, and an optional `complaint_id`. When `complaint_id` is present, the referenced complaint must currently be in `CONFIRMED_ERROR` and its `listing_id` must equal the correction's `listing_id` (else `ERR_CORRECTION_LISTING_MISMATCH`). The target listing must not be `REMOVED` (else `ERR_LISTING_REMOVED`). The allowed keys inside `changes` are exactly the correction-mutable listing fields: `display_name`, `phone`, `accepts_new_patients`, and `office_hours_note`. On create, `submitted_by_user_id` is the caller's `X-User-ID`, status is `SUBMITTED`, and `sla_due_at` is the creation timestamp plus 72 hours.

Verification is performed by a `ComplianceOfficer` and enforces segregation of duties: the verifier's `X-User-ID` must differ from the correction's `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). The correction must be in `SUBMITTED` (else `ERR_CORRECTION_NOT_VERIFIABLE`). An `approve` value of true (the default) transitions the correction to `VERIFIED`: `verified_at` is stamped, `verified_by_user_id` records the verifier, `is_late` is computed as whether `verified_at` falls strictly after `sla_due_at`, the correction's `changes` are applied to the listing's correction-mutable fields (bumping the listing's `version`), and any linked complaint still in `CONFIRMED_ERROR` cascades to `CLOSED` while the listing's `has_confirmed_data_error` flips back to false. An `approve` value of false transitions the correction to `REJECTED`; the linked complaint, if any, remains in `CONFIRMED_ERROR`, the listing's data-error flag remains set, and a fresh correction may be submitted against the same listing.

### 3.7. Adequacy Evaluation: The Ops-Run Checkpoint

Measurement happens inside an `AdequacyEvaluation` epoch. A `NetworkManager` opens one by supplying `measurement_period`, `period_start_date`, and `period_end_date`; the end date must be on or after the start date (else `ERR_INVALID_REQUEST`). At most one evaluation may be `OPEN` at a time — a second open is rejected with `ERR_EVALUATION_ALREADY_OPEN`.

Finalization is the ops-run checkpoint that closes the epoch. It is refused while any `AvailabilityProbe` remains in `SCHEDULED` with a `requested_date` inside the closed interval from `period_start_date` to `period_end_date` (rejected with `ERR_UNRECORDED_PROBES_EXIST`); the rationale is that finalizing over an incomplete probe set would silently undercount wait-time failures. Finalizing an evaluation not in `OPEN` is rejected with `ERR_EVALUATION_INVALID_STATE`. On success, finalization runs a four-link cascade.

Link 1 computes the per-pair result rows. For every `ServiceRegion` crossed with every specialty for which a `NetworkStandard` exists for `(specialty, region.geo_class)`, a `RegionSpecialtyResult` row is created. The row snapshots `member_count` from the region's `enrolled_member_count` at finalize time. It then computes the counted provider set: distinct providers in `EFFECTIVE` status who hold at least one `LISTED` listing of this specialty whose location is in this region and whose location's `panel_status` is `OPEN`. `provider_count` is the size of that set. A separate `listing_count` variant counts the `LISTED` listings themselves — a provider listed at two locations counts twice — so that a regulatory filing can cross-check the official headcount against the listing base. `ratio_members_per_provider` is `member_count` divided by `provider_count`, rounded half-up to 2 decimal places, null when `provider_count` is zero. `ratio_ok` is the integer comparison of `member_count` against the standard's `max_members_per_provider` multiplied by `provider_count`; it is false whenever `provider_count` is zero and `member_count` is positive.

The same row computes time-and-distance compliance. `counted_location_count` is the number of locations hosting the counted `LISTED` listings. A counted location is compliant when its `avg_travel_minutes` is at or below the standard's `max_travel_minutes` and its `avg_travel_miles` is at or below the standard's `max_travel_miles`; `compliant_location_count` tallies these. `time_distance_compliant` is evaluated in integer arithmetic as ten times `compliant_location_count` being at least nine times `counted_location_count` — so the 90% boundary is inclusive and exact, with no float tolerance — and is false when `counted_location_count` is zero and `member_count` is positive.

The same row also computes wait-time compliance over the counted listings. `probed_listing_count` counts the `RECORDED` probes on counted listings whose `recorded_at` date falls inside the closed measurement period and whose `days_to_appointment` is non-null — that is, `KEPT` probes. `mean_wait_days` is the mean of `days_to_appointment` over that probed set, rounded half-up to 2 decimal places, null when the set is empty. `p90_wait_days` is reported alongside for the filing: the probed `days_to_appointment` values are sorted ascending and the value at the 1-based index equal to the ceiling of nine-tenths of the sample size is taken; null when empty. `wait_time_compliant` — the official gate — is true when the probed set is empty, and otherwise is whether `mean_wait_days` is at or below the standard's `max_wait_days_routine`. Only `ROUTINE` probes feed the official gate; `URGENT` probes are excluded. The `p90_wait_days` reading is reported but does not gate, so a tail-heavy sample may pass the mean while flagging on the p90 reading.

The row's `overall_status` is `COMPLIANT` when `member_count` is zero, or when `ratio_ok`, `time_distance_compliant`, and `wait_time_compliant` are all true. Otherwise it is `DEFICIENT` — unless an `APPROVED` `AccessPlanRequest` exists for this `(region, specialty)` pair whose `excuse_through_date` is on or after `period_end_date`, in which case the row is `EXCUSED`. These rows are immutable snapshots: `RegionSpecialtyResult` carries no `updated_at` and no `version`.

Link 2 reconciles deficiencies. For each pair whose `overall_status` came out `DEFICIENT`: if no `OPEN` or `EXCUSED` `DeficiencyRecord` exists for the `(region_id, specialty)` pair, one is created in `OPEN` with `opened_date` set to this evaluation's `period_start_date` and `prior_closure_count` snapshotted to the count of `CLOSED` records for the same pair at the moment of creation. If an `OPEN` one already exists, it is extended. If an `EXCUSED` one exists whose `excuse_through_date` falls before `period_end_date`, the excuse has lapsed and the record reopens — `EXCUSED` → `OPEN` — with the new accrual window running from the later of `period_start_date` and `excuse_through_date` through `period_end_date`. A sibling branch handles the compliant side: each pair that came out `COMPLIANT` and has an existing `OPEN` or `EXCUSED` deficiency has that deficiency transitioned to `CLOSED` with `closed_date` set to `period_end_date` and `version` incremented.

Link 3 accrues penalties on every `OPEN` deficiency touched by this finalize. The accrual is tiered. The tier multiplier is 2.0 when the region's `enrolled_member_count` is at least 50,000; otherwise 1.5 when it is at least 10,000; otherwise 1.0. The repeat multiplier is 1 plus 0.5 times the smaller of the deficiency's `prior_closure_count` and 3 — so the repeat uplift caps at 2.5 times for a fourth-or-later deficiency on the same pair. The accrual window's length in whole calendar days is the difference between `accrual_window_end` and `accrual_window_start`. The raw accrual is the base daily penalty of 9,999 cents multiplied by the day count, multiplied by the tier multiplier, multiplied by the repeat multiplier. The per-event accrual is the smaller of 5,000,000 cents (the cap) and the raw accrual rounded half-up to integer cents. The deficiency's `last_accrual_cents` is set to this event's amount; `accrued_penalty_cents` accumulates it. An `EXCUSED` deficiency whose excuse covers `period_end_date` accrues nothing for this finalize; only when the excuse lapses short of period end does the uncovered tail accrue, via the reopen branch above. The invariant `outstanding_penalty_cents` equals `accrued_penalty_cents` minus `reversed_penalty_cents` holds at all times. This accrual is provisional — it is the exposure the plan books for the measured period now — and is never recomputed retroactively when the deficiency later closes; past windows stand as booked.

Link 4 recomputes the evaluation's `total_penalty_cents`. The rollup has three components. The deficiency component is the sum over this evaluation's accrual events of each event's round-half-up-to-integer-cents amount — per-event rounding happens before summation, not after. The error component is 25,000 cents per `MemberComplaint` whose `confirmed_at` falls inside the measurement period (the period is interpreted as running from the start of `period_start_date` through the end of `period_end_date`) and whose current status is `CONFIRMED_ERROR` or `CLOSED` — that is, ever-confirmed within the period — attributed to the evaluation via the complaint's listing's location's region. The late-correction component is 50,000 cents per `DirectoryCorrection` in `VERIFIED` status with `is_late` true and `verified_at` inside the period. The sum lands on the evaluation's `total_penalty_cents`. The evaluation's `finalized_at` is stamped, `status` transitions to `FINALIZED`, and `version` increments by 1.

A computed penalty-summary read exposes the breakdown: `deficiency_penalties_cents`, `error_penalties_cents`, `late_correction_penalties_cents`, `total_penalty_cents`, and a `rows` array of per-line detail.

### 3.8. Access Plan Requests: The Regulatory Exception Path

When a deficiency opens, the plan may petition the regulator for an access-plan exception. A `NetworkManager` files a new `AccessPlanRequest` against an `OPEN` deficiency (filing against a non-`OPEN` deficiency is rejected with `ERR_DEFICIENCY_NOT_OPEN`), supplying `remedy_summary`, `excuse_start_date`, and `excuse_through_date`. The window's end must be on or after its start, and the start must not be before the current clock date; violations yield `ERR_EXCUSE_WINDOW_INVALID`. The create is OCC-guarded via `expected_deficiency_version`: the caller must present the deficiency's current `version`, and a mismatch is rejected with `ERR_STALE_DEFICIENCY_VERSION`. This is the serialization point that catches a second writer creating a request against a deficiency whose `version` has already been advanced by a prior create — the prior create legitimately superseded an earlier draft, and the current writer's view is stale.

When a new request is created on a deficiency that already has a `DRAFT` request, the older draft transitions to `SUPERSEDED` (its `version` incrementing) and the new request receives `submission_seq` equal to one more than the maximum `submission_seq` over the deficiency's existing requests — the first request on a deficiency gets `submission_seq` 1. The create also increments the deficiency's `version` by 1, which is what the OCC field is observing.

A request in `DRAFT` or `DENIED` may be submitted to the regulator; submission from any other status is rejected with `ERR_REQUEST_NOT_SUBMITTABLE`. A resubmission from `DENIED` resets `decided_at` to null and increments `version`. Submission transitions the request to `SUBMITTED`.

A `Regulator` decides a `SUBMITTED` request (else `ERR_REQUEST_NOT_DECIDABLE`). A `decision` of `DENIED` simply stamps `decided_at` and increments `version`; the request may later be resubmitted. A `decision` of `APPROVED` enforces two additional preconditions: the parent deficiency must currently be `OPEN` (else `ERR_DEFICIENCY_NOT_OPEN`), and the requested excuse window — interpreted as a closed interval, so touching endpoints count as overlap — must not overlap any other `APPROVED` request's window for the same deficiency (else `ERR_EXCUSE_WINDOW_OVERLAP`). On approval, `decided_at` is stamped, `decision_notes` records the optional `notes`, and three cascades fire. The deficiency transitions from `OPEN` to `EXCUSED`. Its outstanding penalty is reversed: `reversed_penalty_cents` increases by the prior outstanding amount, driving `outstanding_penalty_cents` to zero, and the deficiency's `version` increments. The owning evaluation's `total_penalty_cents` is decremented by the same reversed amount.

### 3.9. Member Lifecycle

Members are enrolled into a region by a `NetworkManager` supplying `region_id`, `member_ref` (unique, else `ERR_MEMBER_REF_DUPLICATE`), `full_name`, and `enrolled_on`. The member is born in `ENROLLED`. Disenrollment transitions the member to `DISENROLLED` (terminal) and stamps `disenrolled_at`; attempting to disenroll a member not currently `ENROLLED` is rejected with `ERR_MEMBER_NOT_ENROLLED`. Disenrollment does not propagate to the region's `enrolled_member_count` — that field is an input snapshot, not a derived count, so it stays whatever the `NetworkManager` last set it to.

## 4. Endpoint Definitions

The table below summarizes the HTTP contract. New-resource creation returns HTTP 201; modifications, transitions, and reads return HTTP 200. Error responses use the standard error envelope (§2.2) with the error IDs catalogued in §5. Refer to §3 for the full request payloads, preconditions, and side effects of each operation.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock; sweeps `PENDING_LOAD` providers whose `contract_effective_date` has been reached to `EFFECTIVE` | NetworkManager |
| POST | `/network/regions` | Create a service region | NetworkManager |
| GET | `/network/regions` | List regions (filter: `geo_class`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/regions/{id}` | Get one region | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/standards` | Create an adequacy standard for a `(specialty, geo_class)` pair | NetworkManager |
| GET | `/network/standards` | List standards (filters: `specialty`, `geo_class`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/standards/{id}` | Get one standard | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| PUT | `/network/standards/{id}` | Update standard thresholds (OCC-guarded) | NetworkManager |
| POST | `/network/providers` | Load a new provider | NetworkManager |
| GET | `/network/providers` | List providers (filters: `status`, `specialty`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/providers/{id}` | Get one provider | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| PATCH | `/network/providers/{id}` | Provider lifecycle transition (suspend / reinstate / terminate) | NetworkManager |
| POST | `/network/locations` | Create a practice location | NetworkManager |
| GET | `/network/locations` | List locations (filters: `provider_id`, `region_id`, `panel_status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/locations/{id}` | Get one location | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| PATCH | `/network/locations/{id}` | Update location panel status or travel survey values (OCC-guarded) | NetworkManager |
| POST | `/network/listings` | Create a directory listing in `DRAFT` | NetworkManager |
| GET | `/network/listings` | List listings (filters: `provider_id`, `location_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/listings/{id}` | Get one listing | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/listings/{id}/publish` | Publish a `DRAFT` listing to `LISTED` | NetworkManager |
| PATCH | `/network/listings/{id}` | Listing status transition (OCC-guarded) | NetworkManager |
| POST | `/network/members` | Enroll a member | NetworkManager |
| GET | `/network/members` | List members (filters: `region_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/members/{id}` | Get one member | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/members/{id}/disenroll` | Disenroll a member | NetworkManager |
| POST | `/network/attestation-cycles` | Schedule an attestation cycle | NetworkManager |
| GET | `/network/attestation-cycles` | List attestation cycles (filter: `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/attestation-cycles/{id}` | Get one cycle with computed counters | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/attestation-cycles/{id}/advance` | Advance the cycle state machine | NetworkManager |
| GET | `/network/attestation-records` | List attestation records (filters: `cycle_id`, `listing_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/attestation-records/{id}` | Get one attestation record | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/attestation-records/{id}/respond` | ProviderRep attests accuracy or requests a correction | ProviderRep |
| POST | `/network/probes` | Schedule an appointment-availability probe | NetworkManager |
| GET | `/network/probes` | List probes (filters: `listing_id`, `result`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/probes/{id}` | Get one probe | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/probes/{id}/record` | Record a probe outcome | NetworkManager |
| POST | `/network/evaluations` | Open an adequacy evaluation epoch | NetworkManager |
| GET | `/network/evaluations` | List evaluations (filter: `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/evaluations/{id}` | Get one evaluation | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/evaluations/{id}/finalize` | Finalize the evaluation (4-link cascade) | NetworkManager |
| GET | `/network/evaluations/{id}/penalty-summary` | Penalty exposure breakdown for the evaluation | NetworkManager, ComplianceOfficer, Regulator |
| GET | `/network/results` | List evaluation result rows (filters: `evaluation_id`, `region_id`, `overall_status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/results/{id}` | Get one result row (immutable snapshot) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/deficiencies` | List deficiencies (filters: `evaluation_id`, `region_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/deficiencies/{id}` | Get one deficiency | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/deficiencies/{id}/access-plan-requests` | File a new access plan request on an `OPEN` deficiency (OCC-guarded) | NetworkManager |
| GET | `/network/access-plan-requests` | List access plan requests (filters: `deficiency_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/access-plan-requests/{id}` | Get one access plan request | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/access-plan-requests/{id}/submit` | Submit (or resubmit from `DENIED`) to the regulator | NetworkManager |
| POST | `/network/access-plan-requests/{id}/decide` | Regulator decision (approve or deny) | Regulator |
| POST | `/network/complaints` | Member files a complaint against a listing | Member |
| GET | `/network/complaints` | List complaints (filters: `member_id`, `listing_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/complaints/{id}` | Get one complaint | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/complaints/{id}/adjudicate` | ComplianceOfficer confirms or dismisses a complaint | ComplianceOfficer |
| POST | `/network/corrections` | Manually submit a directory correction | NetworkManager |
| GET | `/network/corrections` | List corrections (filters: `listing_id`, `complaint_id`, `status`) | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| GET | `/network/corrections/{id}` | Get one correction | NetworkManager, ComplianceOfficer, Regulator, ProviderRep, Member |
| POST | `/network/corrections/{id}/verify` | ComplianceOfficer verifies or rejects a correction | ComplianceOfficer |

## 5. Error Code Catalogue

The table below enumerates every error ID and its HTTP status. Trigger conditions are described in §2 and §3 alongside the operations that raise them.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |
| `ERR_REGION_NOT_FOUND` | 404 |
| `ERR_STANDARD_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_LOCATION_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_ATTESTATION_RECORD_NOT_FOUND` | 404 |
| `ERR_PROBE_NOT_FOUND` | 404 |
| `ERR_EVALUATION_NOT_FOUND` | 404 |
| `ERR_DEFICIENCY_NOT_FOUND` | 404 |
| `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_CORRECTION_NOT_FOUND` | 404 |
| `ERR_PROVIDER_INVALID_TRANSITION` | 409 |
| `ERR_PROVIDER_NOT_EFFECTIVE` | 409 |
| `ERR_LISTING_INVALID_TRANSITION` | 409 |
| `ERR_LISTING_NOT_LISTED` | 409 |
| `ERR_LISTING_REMOVED` | 409 |
| `ERR_LISTING_ATTESTATION_UNRESOLVED` | 409 |
| `ERR_LISTING_GHOST_UNRESOLVED` | 409 |
| `ERR_CYCLE_INVALID_STATE` | 409 |
| `ERR_RECORD_NOT_RESPONDABLE` | 409 |
| `ERR_PROBE_INVALID_STATE` | 409 |
| `ERR_EVALUATION_INVALID_STATE` | 409 |
| `ERR_UNRECORDED_PROBES_EXIST` | 409 |
| `ERR_DEFICIENCY_NOT_OPEN` | 409 |
| `ERR_REQUEST_NOT_SUBMITTABLE` | 409 |
| `ERR_REQUEST_NOT_DECIDABLE` | 409 |
| `ERR_COMPLAINT_NOT_OPEN` | 409 |
| `ERR_CORRECTION_NOT_VERIFIABLE` | 409 |
| `ERR_MEMBER_NOT_ENROLLED` | 409 |
| `ERR_NPI_DUPLICATE` | 409 |
| `ERR_REGION_DUPLICATE` | 409 |
| `ERR_MEMBER_REF_DUPLICATE` | 409 |
| `ERR_STANDARD_DUPLICATE` | 409 |
| `ERR_LISTING_ALREADY_LISTED` | 409 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_CYCLE_ALREADY_ACTIVE` | 409 |
| `ERR_EXCUSE_WINDOW_OVERLAP` | 409 |
| `ERR_EVALUATION_ALREADY_OPEN` | 409 |
| `ERR_CYCLE_NOT_YET_ADVANCEABLE` | 422 |
| `ERR_COMPLAINT_WINDOW_EXPIRED` | 422 |
| `ERR_PROBE_DATE_ORDER` | 422 |
| `ERR_EXCUSE_WINDOW_INVALID` | 422 |
| `ERR_LOCATION_PROVIDER_MISMATCH` | 422 |
| `ERR_LISTING_NOT_IN_MEMBER_REGION` | 422 |
| `ERR_CORRECTION_LISTING_MISMATCH` | 422 |
| `ERR_SPECIALTY_STANDARD_MISSING` | 422 |
| `ERR_STALE_STANDARD_VERSION` | 412 |
| `ERR_STALE_LOCATION_VERSION` | 412 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_STALE_DEFICIENCY_VERSION` | 412 |

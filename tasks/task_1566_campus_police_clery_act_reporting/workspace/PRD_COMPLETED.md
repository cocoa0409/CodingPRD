# Campus Police Clery API — Product Requirements Document

## 1. Introduction

The Jeanne Clery Disclosure of Campus Security Policy and Campus Crime Statistics Act imposes a year-round operational burden on campus police departments that extends far beyond publishing a PDF every October. Incidents must be captured, classified against Clery geography categories, counted under the federal hierarchy rule, logged daily for public inspection, and rolled into the Annual Security Report — all while timely-warning obligations run on forty-eight-hour decision clocks and campus security authorities must be trained, certified, and kept current. When the Department of Education opens a program review, the institution must also track findings and corrective actions through verification without letting scope overlap across open reviews.

This document specifies the REST API of a campus police Clery Act compliance platform covering that full surface: incident intake from three channels (direct police reports, campus security authority referrals, anonymous tips), offense counting and hierarchy resolution, timely warning and emergency notification workflows with enforced segregation of duties, daily crime log maintenance with public transparency, the Annual Security Report compile-publish-amend lifecycle with snapshot versioning, the fire safety report for residential facilities, CSA certification management, and federal program review remediation. A logical clock under administrative control governs every deadline and staleness evaluation, and optimistic concurrency control protects the two snapshot-producing operations (incident classification and report compilation) from silent overwrites.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting principal and `X-User-Role` naming the acting role. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The platform recognizes exactly six roles, spelled exactly as follows:

- `SystemAdmin` — the campus police system administrator; owns configuration entities (geographies, CSAs, report shells) and the logical clock. `X-User-ID` for a `SystemAdmin` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- `CleryCoordinator` — the compliance coordinator who classifies incidents, decides alerts, compiles and amends reports, fulfills inspection requests, and submits corrective actions. `X-User-ID` for a `CleryCoordinator` is an opaque operator identifier not tied to any persisted entity. When an alert decision is recorded, the coordinator's `X-User-ID` is written into the alert's `decided_by`, but no ownership comparison against entity `id` values is performed for the role.
- `PoliceChief` — the chief of campus police; unfounds incidents, authorizes and disseminates alerts, sets log dispositions, publishes reports, and finalizes fire incidents. `X-User-ID` for a `PoliceChief` is an opaque operator identifier not tied to any persisted entity. The chief's `X-User-ID` is recorded as `authorized_by` on alerts at authorization time, without any entity-`id` comparison.
- `CampusSecurityAuthority` — a trained campus security authority filing referral reports. When `X-User-Role` is `CampusSecurityAuthority`, `X-User-ID` is the `id` of the acting `CampusSecurityAuthority` entity; ownership checks on any resource that references a `CampusSecurityAuthority` compare the resource's foreign-key field to `X-User-ID`. A CSA acting on another CSA's referral report is rejected with `ERR_FORBIDDEN`.
- `FederalReviewer` — a Department of Education program reviewer. `X-User-ID` for a `FederalReviewer` is an opaque operator identifier not tied to any persisted entity.
- `Anonymous` — an unauthenticated-equivalent public role for crime log transparency; the caller still sends `X-User-Role: Anonymous` with an `X-User-ID` that is an opaque identifier not tied to any persisted entity.

Segregation of duties is deliberate: the role that decides an alert (`CleryCoordinator`) may not authorize or disseminate it (`PoliceChief`), and the role that compiles a report (`CleryCoordinator`) may not publish it (`PoliceChief`).

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

All list endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10; its minimum accepted value is 1 and its maximum is 100. The default `offset` is 0. A `limit` or `offset` parameter that is not a well-formed integer, or that falls outside the bounds above, is rejected with `ERR_VALIDATION_FAILED` (HTTP 422). List responses are always sorted by `created_at` ascending, with stable creation order breaking any timestamp ties. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full size of the filtered result set and `has_more` indicates whether additional rows exist beyond the returned window.

### 2.4. The Logical Clock

The platform runs on a server-side logical clock, not wall-clock time. Before any call to the clock-control capability, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `SystemAdmin` advances the clock by calling the clock-control capability with a `to_iso8601` instant; the response echoes the client's `to_iso8601` string unchanged as `current_utc`. Every deadline, overdue flag, expiration, staleness marker, and year-membership decision in this document is evaluated against this logical clock.

Time-driven system transitions are evaluated lazily: passing the certification expiry of a `CampusSecurityAuthority` or the `valid_to` of a `CSATrainingRecord` takes effect when the logical clock has moved past the threshold and the relevant entity is next read or acted upon, at which point the CSA flips from `ACTIVE` to `LAPSED` and the record flips from `ACTIVE` to `EXPIRED`.

### 2.5. Common Resource Properties and Concurrency Control

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp of the same format refreshed on every mutation, and an integer `version` that increments by one on every mutation. Any request body containing a required field that is missing, or a field of a malformed type, is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any deeper validation runs.

Server-stamped timestamp fields on resources beyond that common pair — event stamps and computed deadlines such as `received_at`, `forwarded_at`, `classified_at`, `decided_at`, `authorized_at`, `disseminated_at`, `closed_at`, `compiled_at`, `published_at`, `amendment_started_at`, `requested_at`, `fulfilled_at`, `last_disposition_change_at`, `decision_deadline_at`, `dissemination_deadline_at`, `due_at`, `provisional_due_at`, and `valid_to` — are likewise ISO 8601 UTC, but an instant falling exactly on a whole second renders without fractional digits (the `2026-08-01T00:00:00Z` style of §2.4), while an instant carrying sub-second precision renders with three fractional digits. Timestamp fields that echo a client-supplied value — `reported_at`, `occurred_at`, `occurred_end_at`, `completed_at`, `valid_from`, and the log entry's `date_reported` and `date_occurred` — or that copy another field's value — `opened_at` copies the review's `created_at`, and a CSA's `certification_expires_at` copies the conferring record's `valid_to` — keep the source value unchanged.

Two write operations are protected by optimistic concurrency control, because each supersedes a snapshot another caller may be acting on:

- Classification of an incident requires the request to carry `expected_incident_version` equal to the incident's current `version`. If another writer has advanced the incident's version since the caller last read it — for example by completing a classification whose new offense set legitimately supersedes the rows the caller was looking at — the classify call is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from silently overwriting a classification it never observed.
- Compiling an Annual Security Report requires `expected_report_version` equal to the report's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a successful compile supersedes the prior statistics snapshot and a caller holding a stale version must not overwrite a snapshot it never saw.

Endpoints not listed above take no version field at all.

### 2.6. Reference Resolution and Validation Priority

Path-template identifiers resolve left to right along nested URLs — incident, then alert; report, then statistic line; review, then corrective action; CSA, then training record — and any identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404). Foreign keys carried in a request body, namely `geography_id` and `referral_id`, resolve separately and produce `ERR_REFERENCE_NOT_FOUND` (HTTP 404) when the referenced entity does not exist.

When a request trips several rules at once, failures surface in a fixed priority order so that earlier, cheaper rejections are never masked by later ones: authentication first (missing headers), then authorization (role and CSA ownership), then request-shape validation (which runs against the request body as soon as the body has been read, and so can precede path resolution on operations that parse the body first), then path resolution, then body foreign-key resolution, then state-machine legality (including terminal-incident guards, the anonymous-visibility guard, and OCC stale-version rejection), then business-safety rules (unfound justification, CSA certification, classification completeness, locked reports), then temporal business rules (the alert reopen window), then structural business constraints (duplicate report years, overlapping review scopes, overlapping training windows, duplicate active alerts, final-compile and recompile gates, unresolved-action gates), then referential business rules (retired or in-use geographies, residential-facility requirements, referral linkage state), and finally field-level value constraints (enum membership, numeric ranges, date ordering, channel sets).

### 2.7. Precision and Rounding

Offense hierarchy ranks, victim counts, referral person counts, statistic cell counts, penalty scores, weights, and escalation thresholds are integers with no rounding applied. Fire damage is the one rounded quantity in the system: adjudicated damage is rounded half up to zero decimal places — whole dollars — at the moment a fire incident is finalized, and the rounded per-incident value is persisted before any aggregation. Fire report totals sum the already-rounded per-incident values; the sum itself is never rounded. Deadline comparisons (the 48-hour warning decision, the 24-hour dissemination window, the 72-hour reopen window, the CSA certification window) compare at second granularity. Crime-log timeliness and inspection-fulfillment windows compare at day granularity using business days; the informational provisional inspection deadline compares elapsed hours.

### 2.8. Common Date-Range and Field Constraints

Across every endpoint that accepts a range, the end bound must not precede the start bound: `occurred_end_at` must be greater than or equal to `occurred_at`, `to_date` must be greater than or equal to `from_date`, `scope_year_end` must be greater than or equal to `scope_year_start`, and a corrective action's `due_date` must be greater than or equal to the date portion of its parent review's `opened_at`. Enum fields accept only their declared members; a training `score` is an integer from 0 to 100; `victim_count` is at least 1; monetary amounts are at least 0; and `distribution_channels` at dissemination time must be a non-empty subset of `EMAIL`, `SMS`, `POSTERS`, `WEBSITE`, `SIREN`. Violations of these field-level constraints are rejected with `ERR_VALIDATION_FAILED` (HTTP 422); a dissemination attempt with an empty channel set is rejected with the more specific `ERR_NO_DISTRIBUTION_CHANNELS` (HTTP 422).

---

## 3. Business Logic & Workflows

### 3.1. Clery Geography Registry

A `CleryGeography` is the institution's map for Clery counting purposes. A `SystemAdmin` registers each zone with a `name`, a `category` drawn from `ON_CAMPUS`, `ON_CAMPUS_RESIDENTIAL`, `NON_CAMPUS`, or `PUBLIC_PROPERTY`, and an `is_residential_facility` flag (defaulting to false) that is true only for on-campus student housing facilities and is a precondition for reporting a fire against that zone. New geographies are born `ACTIVE` and carry a `status` that later moves to `RETIRED`.

The geography update accepts any combination of `name`, `is_residential_facility`, and `status`; supplied fields replace the stored values, and omitted fields are left unchanged. Retirement is guarded from two directions. In one direction, any operation that references a geography — incident creation, incident classification, referral creation, or fire-incident creation — requires the geography's `status` to be `ACTIVE` and is rejected with `ERR_GEOGRAPHY_RETIRED` (HTTP 422) otherwise. In the other direction, a geography cannot be retired while any non-terminal incident report (any incident not in `UNFOUNDED` or `WITHDRAWN`) or any fire incident still references it; such an update is rejected with `ERR_GEOGRAPHY_IN_USE` (HTTP 409). Listing geographies supports optional `category` and `status` filters.

### 3.2. Incident Intake and the CSA Referral Channel

Incident reports enter the system in three ways, recorded on the `source` field: `POLICE_DIRECT`, `CSA_REFERRAL`, or `ANONYMOUS`. A `CleryCoordinator` or `PoliceChief` creates the report with `reported_at` (when campus police learned of it), `occurred_at` (when it happened — the calendar year of this timestamp fixes the incident's Annual Security Report year membership), an optional `occurred_end_at`, a `geography_id` that may be confirmed or replaced at classification time, and a free-text `narrative`. The server mints a `report_number` of the form IR-<year>-<seq6>, where the year is the calendar year of `reported_at` and the sequence is a per-server counter over all incident reports; any client-supplied value is ignored. New incidents are born `DRAFT`, with `is_clery_reportable` false and `classified_at` unset.

When `source` is `CSA_REFERRAL`, the create must carry a `referral_id` identifying the referral report being converted, and that referral must currently be in `FORWARDED` status; a missing or inappropriately-stated referral produces `ERR_INVALID_STATE` (HTTP 409), while an unresolvable identifier produces `ERR_REFERENCE_NOT_FOUND`. For any other `source`, `referral_id` must be absent. On successful creation with a referral, the referral transitions `FORWARDED → LINKED` and the new incident's `referral_id` is set. The incident list supports `status`, `geography_id`, `referral_id`, and `report_year` filters, the last matching on the calendar year of `occurred_at`; a `report_year` value that is not a well-formed integer matches no incidents rather than failing the request.

The referral channel itself works as follows. A `CampusSecurityAuthority` files a `CSAReferralReport` carrying the caller's own identity — `csa_id` is taken from the caller's `X-User-ID`, never from the body — plus `geography_id`, `occurred_at`, an optional `occurred_end_at`, an `offense_suspicion` drawn from the same offense enumeration used for offense counting, and a `narrative`. Filing is only possible while the caller CSA is `ACTIVE`; a referral from a `PENDING_TRAINING`, `LAPSED`, or `INACTIVE` authority — or from an `X-User-ID` that does not resolve to any registered CSA — is rejected with `ERR_CSA_NOT_CERTIFIED` (HTTP 422). The report is born `RECEIVED`, with `received_at` set to its creation time and `forwarded_at` null.

From `RECEIVED`, the CSA forwards the report to campus police; only the owning CSA may forward — a caller whose `X-User-ID` does not equal the report's `csa_id` is rejected with `ERR_FORBIDDEN`. Forwarding stamps `forwarded_at` and computes `forward_overdue`, which is true when the forward happened strictly more than 24 hours after `received_at` and false when it happened within or exactly at 24 hours. A `CleryCoordinator` may instead mark a `RECEIVED` or `FORWARDED` referral as `DUPLICATE` when it duplicates an already-known incident; marking from any other status is rejected with `ERR_INVALID_STATE`. Once linked, a referral is terminal, as is a duplicate. When a CSA caller lists referral reports, only their own are visible, and the `csa_id` filter narrows further within that visibility set rather than widening it; staff roles see all and may filter by `csa_id`, `status`, or `geography_id`.

### 3.3. Classification and the Offense Hierarchy

Classification is where an incident becomes a Clery statistic. Submission first: a `DRAFT` incident is submitted by a `CleryCoordinator` or `PoliceChief` — attempting submission from any other state yields `ERR_INVALID_STATE` — which transitions it `DRAFT → SUBMITTED`, increments its `version`, and has an important side effect described in §3.4. From `SUBMITTED`, a coordinator begins classification, moving the incident `SUBMITTED → UNDER_CLASSIFICATION`. From `CLASSIFIED`, a coordinator may begin reclassification, moving `CLASSIFIED → UNDER_RECLASSIFICATION`; both classification paths then converge on the same classify operation, which returns the incident to `CLASSIFIED`.

The classify call carries a `geography_id` (confirming or replacing the intake geography), an `offense_counts` array describing each offense, and the OCC field `expected_incident_version` per §2.5. The elements of `offense_counts` are validated for shape — each must be an object whose `offense_type` is a string and whose `victim_count`, `referred_persons`, and `bias_motivation`, when present, are of the declared types — before any state-machine or staleness evaluation; a malformed element is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Two business-safety guards apply before any offense math: the array must be non-empty and contain at least one offense whose type is not `NON_CLERY`, otherwise the call is rejected with `ERR_CLASSIFICATION_INCOMPLETE` (HTTP 422); and begin-reclassification is forbidden outright with `ERR_REPORT_LOCKED` (HTTP 409) whenever the Annual Security Report covering the calendar year of the incident's `occurred_at` exists in `PUBLISHED` or `REPUBLISHED` status — published disclosures freeze their underlying classifications.

Each element of `offense_counts` names an `offense_type` from the enumeration `CRIMINAL_HOMICIDE`, `SEX_OFFENSE`, `ROBBERY`, `AGGRAVATED_ASSAULT`, `BURGLARY`, `MOTOR_VEHICLE_THEFT`, `ARSON`, `DOMESTIC_VIOLENCE`, `DATING_VIOLENCE`, `STALKING`, `HATE_CRIME`, `LIQUOR_LAW_REFERRAL`, `DRUG_LAW_REFERRAL`, `WEAPONS_LAW_REFERRAL`, `NON_CLERY`; a `victim_count` defaulting to 1 and at least 1; a `referred_persons` count defaulting to 0, never negative, and only meaningful for the three referral offense types; and a `bias_motivation` defaulting to `NONE` and otherwise one of `RACE`, `RELIGION`, `SEXUAL_ORIENTATION`, `GENDER`, `GENDER_IDENTITY`, `ETHNICITY`, `NATIONAL_ORIGIN`, `DISABILITY`. Classification replaces the incident's entire prior offense row set with the submitted set.

The hierarchy rule then decides what counts. Each offense receives a `hierarchy_rank` from the fixed rank table: `CRIMINAL_HOMICIDE` ranks 10, `SEX_OFFENSE` 20, `ROBBERY` 30, `AGGRAVATED_ASSAULT` 40, `BURGLARY` 50, `MOTOR_VEHICLE_THEFT` 60, `ARSON` 70, `DOMESTIC_VIOLENCE` 80, `DATING_VIOLENCE` 81, `STALKING` 82, `HATE_CRIME` 90, `LIQUOR_LAW_REFERRAL` 100, `DRUG_LAW_REFERRAL` 101, `WEAPONS_LAW_REFERRAL` 102, and `NON_CLERY` 999; client-supplied rank input is ignored. An offense is marked `is_exempt_from_hierarchy` true when its type is `ARSON`, `DOMESTIC_VIOLENCE`, `DATING_VIOLENCE`, `STALKING`, `HATE_CRIME`, or any of the three referral types. Every `NON_CLERY` offense is assigned `status` `EXCLUDED_BY_HIERARCHY` without exception. Among the remaining non-exempt offenses, the primary offense is the one with the smallest `hierarchy_rank`, with ties broken by earliest submission order within the classify call's array — never by record id. The primary offense and every exempt offense are assigned `status` `COUNTED`; all other non-exempt offenses are `EXCLUDED_BY_HIERARCHY`. The label used for the log-entry rewrite of §3.4 is the primary offense's type when a primary exists; otherwise, when the incident still has `COUNTED` rows (all of them exempt), it is the `COUNTED` row with the smallest `hierarchy_rank`, ties broken by earliest submission order; an offense set that counts nothing leaves the label at "Unclassified". After a successful classification the incident's `is_clery_reportable` becomes true as soon as at least one offense row is `COUNTED`, and `classified_at` records the timestamp of the most recent successful classify. The incident's offense-row listing returns the current rows in submission order — the order in which the rows were arrayed in the most recent successful classify call.

Classification and reclassification differ in one cascade. When a reclassification succeeds and an Annual Security Report for the calendar year of `occurred_at` exists in `COLLECTING` or `UNDER_AMENDMENT` status with a `statistics_version` greater than 0, that report's `statistics_stale` flag is set true and all of its `CURRENT` statistic lines are flipped to `SUPERSEDED`, signaling that the published pipeline has drifted from the underlying data. Reports in any other status, and reports not yet compiled, are untouched by this cascade.

An incident leaves the active pipeline in two ways. A `DRAFT` incident may be withdrawn by a `CleryCoordinator`, transitioning `DRAFT → WITHDRAWN`. More consequentially, a `PoliceChief` may unfound an incident from `UNDER_CLASSIFICATION`, `UNDER_RECLASSIFICATION`, or `CLASSIFIED`; the unfound call must carry a non-empty `justification` or be rejected with `ERR_UNFOUNDED_JUSTIFICATION_REQUIRED` (HTTP 422). Attempting any incident action from the terminal states `UNFOUNDED` or `WITHDRAWN` is rejected with `ERR_INCIDENT_TERMINAL` (HTTP 409) rather than the generic state error. Unfounding triggers the three-link cascade detailed in §3.5. Every incident state transition increments the incident's `version` by one.

### 3.4. The Daily Crime Log and Public Inspection

The daily crime log is the public-facing shadow of the incident pipeline. Submitting an incident creates exactly one `DailyCrimeLogEntry` for it — never more, never fewer — with a server-minted `entry_number` of the form CL-<seq6> that is unique and never reused. The entry copies `date_reported` from the incident's `reported_at` and `date_occurred` from its `occurred_at`, starts with `nature` set to the literal label "Unclassified", `general_location` null, and `last_disposition_change_at` null, and opens with `disposition` `OPEN`. On every successful classification, the entry's `nature` is rewritten to the primary offense label and its `general_location` to the geography's name at classification time.

Timeliness is tracked with two flags computed against business days, where the count of business days between two instants means the number of dates strictly after the earlier date, up to and including the later date, that fall on a Monday through Friday. `entry_overdue` is set at entry creation and is true when more than 2 business days elapsed between the incident's `reported_at` and the entry's creation. `disposition_update_overdue` is recomputed at every disposition mutation: it is true when more than 2 business days elapsed between the triggering decision instant and the mutation's `last_disposition_change_at`, where the decision instant is the logical clock at the moment the underlying decision occurred — for the unfound cascade, the unfound transition time; for a manual disposition change, the change time itself, so a manual update is never self-overdue.

A `PoliceChief` moves an entry's disposition through a small machine: `OPEN → INVESTIGATION_PENDING`; from `INVESTIGATION_PENDING` to `CLEARED_BY_ARREST` or `CLEARED_EXCEPTIONAL`; from either cleared state back to `OPEN` on reopen; and from `INVESTIGATION_PENDING` back to `OPEN`. Each mutation refreshes `last_disposition_change_at` and recomputes `disposition_update_overdue`. The request body carries the target `disposition`. A target equal to `UNFOUNDED` is rejected with `ERR_INVALID_STATE` (HTTP 409) — that disposition arrives only via the incident-unfound cascade, never through this endpoint — and a target naming any other valid disposition but outside the pairs above is likewise rejected with `ERR_INVALID_STATE`, while a target outside the disposition enumeration entirely is rejected with `ERR_VALIDATION_FAILED` (HTTP 422).

Public transparency has teeth. An entry's `is_public` is false when its parent incident is `DRAFT`, `WITHDRAWN`, or `UNFOUNDED`, and true otherwise; it is derived from the parent incident's current status on every read and serialization. The crime log is readable by the `Anonymous` role as well as staff; anonymous callers see only public entries, and anonymous access to a non-public entry — directly or through the single-entry read — is rejected with `ERR_ENTRY_NOT_PUBLIC` (HTTP 403). A staff caller who passes a truthy `include_unfounded` parameter value (`true`, `1`, or `yes`, case-insensitive) sees all entries, including every non-public one; omitting it or passing any other value restricts the staff list to public entries as well. The log list also supports `from_date`, `to_date`, `disposition`, and `incident_id` filters, the date bounds comparing against the date portion of each entry's `date_occurred`.

Any member of the public may file a `LogInspectionRequest` with `requester_name`, `requester_contact`, and an inclusive date window from `from_date` to `to_date`. Fulfillment timing is governed by two deadline variants computed at creation, one authoritative and one informational. The authoritative CALENDAR_DATE variant defines the matching set as all log entries whose `date_occurred` date portion falls inside the requested window, computes a threshold date of the request date (the date portion of `requested_at`) minus 60 calendar days, and grants immediate access when the earliest matching entry's date is greater than or equal to that threshold — an entry dated exactly 60 days before the request date qualifies regardless of time of day. When every matching entry qualifies, or when the match set is empty, the request is born `FULFILLED` with `fulfilled_at` equal to `requested_at` and `due_at` equal to `requested_at`. Otherwise the request is born `PENDING` with `due_at` set to `requested_at` advanced by 2 business days, skipping Saturdays and Sundays and preserving the time of day. The informational ELAPSED_HOURS variant computes, for display only, each matching entry's age in hours from its `date_occurred` to `requested_at` and considers the entry within the immediate window when that age is at most 1440 hours inclusive — the same 60 days measured as elapsed hours; `provisional_due_at` is `requested_at` when all matching entries pass that test and the 2-business-day deadline otherwise, so an entry 60 days and a few hours old fails the provisional test while still passing the authoritative one. A `PENDING` request becomes `is_overdue` true the moment the logical clock passes `due_at`; a `CleryCoordinator` fulfills a pending request, stamping `fulfilled_at` and moving it `PENDING → FULFILLED`, which is its terminal state.

### 3.5. Statistics Compilation and the Annual Security Report

An `AnnualSecurityReport` shell is created by a `SystemAdmin` for a given `report_year`, which must be unique across all ASRs — a duplicate year is rejected with `ERR_DUPLICATE_REPORT_YEAR` (HTTP 409). The shell is born `COLLECTING` with `statistics_version` 0, `final_compile_done` false, and `statistics_stale` false.

Compilation is the heart of the ASR and runs in a pinned four-step order that removes any circularity between incident inclusion and report state. First, the incident set is frozen: every incident whose `occurred_at` calendar year equals `report_year` and whose status is in the variant's inclusion set, evaluated as of compile time. Second, only offense rows in `COUNTED` status are kept. Third, each counted row maps into geography columns per the incident's geography `category`: an `ON_CAMPUS` incident increments only the `ON_CAMPUS` column; an `ON_CAMPUS_RESIDENTIAL` incident increments both the `ON_CAMPUS` and the `ON_CAMPUS_RESIDENTIAL` columns (on-campus residential counts are a subset of on-campus counts); a `NON_CAMPUS` incident increments only `NON_CAMPUS`; a `PUBLIC_PROPERTY` incident increments only `PUBLIC_PROPERTY`. Fourth, one `StatisticLine` is emitted per `offense_type`-and-`geography_column` cell whose `count` is greater than zero or whose `referred_persons_count` is greater than zero; empty cells produce no row at all. For the three referral offense types, each cell's `referred_persons_count` accumulates the offense rows' `referred_persons` values — persons referred for disciplinary action, not incidents — while non-referral cells carry zero. Each emitted line belongs to the report through its `report_id`, stamps the new `statistics_version` as its snapshot membership, and records whether the compile was `PROVISIONAL` or `FINAL` in its `compilation_variant`; only lines whose `statistics_version` equals the report's current `statistics_version` are `CURRENT`, and the compile flips all previously `CURRENT` lines to `SUPERSEDED`.

Two variants exist by design, selected by the `variant` input on the compile call. A `FINAL` compile includes only incidents in `CLASSIFIED` status and, on success, sets the report's `final_compile_done` true. A `PROVISIONAL` compile additionally includes incidents in `UNDER_RECLASSIFICATION`, counted at their last known offense rows. Incidents in `DRAFT`, `SUBMITTED`, `UNDER_CLASSIFICATION`, `UNFOUNDED`, or `WITHDRAWN` are excluded from both variants, always. Compiling is permitted while the report is `COLLECTING` or `UNDER_AMENDMENT`, requires the OCC field `expected_report_version` per §2.5, and on success increments `statistics_version` by one, sets `statistics_stale` false, stamps `compiled_at`, and increments the report's `version`.

The unfound cascade threads through this structure. When an incident is unfounded, three links fire in order: the incident's log entry is set to `disposition` `UNFOUNDED` with `is_public` false and `last_disposition_change_at` refreshed; because the log entry mutated, the ASR covering the incident's year, if its `statistics_version` is greater than 0, gets `statistics_stale` true regardless of the report's own status; and because `statistics_stale` flipped true, all of that report's `CURRENT` statistic lines become `SUPERSEDED`. All of the incident's offense rows become `EXCLUDED_UNFOUNDED`, and the incident's `is_clery_reportable` is reset to false. The staleness clears on the next successful compile.

The publication lifecycle gates on compilation. A coordinator submits the report for review — `COLLECTING → UNDER_REVIEW` — only after at least one successful `FINAL` compile; otherwise the call is rejected with `ERR_FINAL_COMPILE_REQUIRED` (HTTP 422). A `PoliceChief` publishes from `UNDER_REVIEW`, stamping `published_at` and computing `is_late`, which is true when publication happened strictly after October 1 of the year following `report_year` at 00:00:00 UTC — publishing exactly at that instant is on time. A published or republished report can be amended: begin-amendment moves `PUBLISHED` or `REPUBLISHED → UNDER_AMENDMENT` and stamps `amendment_started_at`. Republication by the chief requires a compile strictly newer than `amendment_started_at` — that is, `compiled_at` must be later than `amendment_started_at` — otherwise the call fails with `ERR_RECOMPILE_REQUIRED` (HTTP 422); success moves the report `UNDER_AMENDMENT → REPUBLISHED` and refreshes `published_at` and `is_late`. Statistic lines are queryable with `compilation_variant`, `geography_column`, `offense_type`, and `statistics_version` filters, defaulting to the current snapshot — that is, to the lines whose `statistics_version` equals the report's current `statistics_version`; a `statistics_version` value that is not a well-formed integer matches no lines rather than failing the request.

### 3.6. Timely Warnings and Emergency Notifications

Every incident that is at least submitted may carry a `SafetyAlert` assessment — opened by a `CleryCoordinator` naming an `alert_type` of `TIMELY_WARNING` or `EMERGENCY_NOTIFICATION`. Creation requires the parent incident to be in `SUBMITTED`, `UNDER_CLASSIFICATION`, `CLASSIFIED`, or `UNDER_RECLASSIFICATION`; an incident still `DRAFT`, or already `UNFOUNDED` or `WITHDRAWN`, cannot spawn an alert and yields `ERR_INVALID_STATE`. At most one alert per incident may exist in a non-`CLOSED` status at any time; opening a second live alert is rejected with `ERR_DUPLICATE_ACTIVE_ALERT` (HTTP 409). A new alert is born `PENDING_REVIEW` with `decision`, `decision_rationale`, `decided_by`, `decided_at`, `authorized_by`, `authorized_at`, `dissemination_deadline_at`, `distribution_channels`, `disseminated_at`, and `closed_at` all null and both overdue flags false.

The alert pipeline enforces segregation of duties. A `CleryCoordinator` records the decision with a `decision` of `ISSUE` or `NO_ISSUE` and a required `decision_rationale` — one that is missing or blank is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — moving the alert `PENDING_REVIEW → DECIDED_ISSUE` or `PENDING_REVIEW → DECIDED_NO_ISSUE` and stamping `decided_at` and `decided_by`. The decision deadline `decision_deadline_at` is fixed at the incident's `reported_at` plus 48 hours, and `decision_overdue` is true when `decided_at` is strictly later than that deadline — deciding exactly at the 48-hour mark is on time. For an `ISSUE` decision, a `PoliceChief` then authorizes dissemination, moving `DECIDED_ISSUE → AUTHORIZED`, stamping `authorized_at` and `authorized_by`, and fixing `dissemination_deadline_at` at `authorized_at` plus 24 hours. The chief disseminates via a non-empty `distribution_channels` set, moving `AUTHORIZED → DISSEMINATED`, stamping `disseminated_at`, and computing `dissemination_overdue`, true when dissemination happened strictly after the dissemination deadline. Either terminal branch of the decision — disseminated, or decided not to issue — is closed by a coordinator, moving `DISSEMINATED → CLOSED` or `DECIDED_NO_ISSUE → CLOSED` and stamping `closed_at`.

Closure is not necessarily final. Within 72 hours of `closed_at` a coordinator may reopen the alert, returning it `CLOSED → PENDING_REVIEW` with `reason` recorded on the alert as `reopen_reason` and every decision field reset: `decision`, `decided_at`, `authorized_at`, `disseminated_at`, and `closed_at` all return to null, and both overdue flags reset to false. The reset is deliberately partial: `decision_rationale`, `decided_by`, `authorized_by`, `distribution_channels`, and the computed `decision_deadline_at` and `dissemination_deadline_at` keep the values they held at closure. A reopen attempted more than 72 hours after closure is rejected with `ERR_ALERT_WINDOW_EXPIRED` (HTTP 422); reopening exactly at the 72-hour mark is permitted.

### 3.7. CSA Certification and Training Records

A `SystemAdmin` registers each `CampusSecurityAuthority` with `full_name`, `email`, `department`, and a `csa_category` of `DEAN`, `COACH`, `RESIDENT_ADVISOR`, `SECURITY_STAFF`, or `OTHER_OFFICIAL`. A new CSA is `PENDING_TRAINING` with `certification_expires_at` null until its first passing training record and `active_training_record_id` null. The CSA list supports `status` and `active_training_record_id` filters.

Certification is conferred by training records, entered by a `SystemAdmin` with `completed_at` and an integer `score` from 0 to 100. Training cannot be recorded for an `INACTIVE` CSA — such an attempt is rejected with `ERR_INVALID_STATE` (HTTP 409). Every recorded training record is born `ACTIVE`. A score of at least 80 passes — exactly 80 passes. Each record derives `passed` from that threshold, `training_year` as the calendar year of `completed_at`, `valid_from` equal to `completed_at`, and `valid_to` as September 30 of the year after `training_year` at 23:59:59 UTC — rendered in the whole-second style of §2.5 — defining a half-open validity window that includes `valid_from` and excludes `valid_to`. A new passing record is rejected with `ERR_TRAINING_WINDOW_OVERLAP` (HTTP 409) whenever any existing record of the same CSA has a window overlapping the new one — that is, the existing record's `valid_from` is earlier than the new record's `valid_to` and the new record's `valid_from` is earlier than the existing record's `valid_to`. Adjacency is not overlap: a new record whose `valid_from` equals an existing record's `valid_to` is permitted.

A passing record recorded while the CSA is `PENDING_TRAINING` or `LAPSED` flips the CSA to `ACTIVE`, sets `certification_expires_at` to the new record's `valid_to`, and points `active_training_record_id` at the new record. A passing record recorded while the CSA is already `ACTIVE` is likewise accepted and re-certifies: the CSA remains `ACTIVE`, and `certification_expires_at` and `active_training_record_id` are refreshed to the new record. When the logical clock passes `certification_expires_at`, the CSA transitions `ACTIVE → LAPSED` and the training record currently conferring certification flips `ACTIVE → EXPIRED`; both transitions are evaluated lazily per §2.4. A `SystemAdmin` may deactivate a CSA from any status except `INACTIVE` itself, moving it to the terminal `INACTIVE` state; a deactivation attempt on an already-inactive CSA yields `ERR_INVALID_STATE`.

### 3.8. Fire Incidents and the Fire Safety Report

Fires in on-campus student housing are tracked in a parallel disclosure. A `CleryCoordinator` or `PoliceChief` reports a `FireIncident` with `geography_id`, `occurred_at` (whose calendar year fixes report-year membership), a `cause_category` of `COOKING`, `ELECTRICAL`, `HEATING`, `SMOKING_MATERIALS`, `OPEN_FLAME`, `INTENTIONAL`, or `UNDETERMINED`, `injuries` and `deaths` each defaulting to 0 and never negative, and an `estimated_damage_dollars` pre-adjudication estimate that is at least 0. The referenced geography must satisfy two constraints beyond existence: its `status` must be `ACTIVE` per the general rule, and `is_residential_facility` must be true — a fire reported against a non-residential zone is rejected with `ERR_RESIDENTIAL_FACILITY_REQUIRED` (HTTP 422). A fire incident is born `REPORTED` with `final_damage_dollars` null. The fire incident list supports `geography_id`, `status`, and `report_year` filters.

A `PoliceChief` finalizes a `REPORTED` or `UNDER_ADJUSTMENT` incident by supplying `adjudicated_damage_dollars`; the system rounds that value half up to zero decimal places, persists the whole-dollar result as `final_damage_dollars`, and moves the incident to `FINALIZED`. A finalized incident may later be reopened into `UNDER_ADJUSTMENT` by the chief, and finalized again. Both finalize and begin-adjustment fire a two-link cascade into the year's fire safety report: the `FireSafetyReport` for the calendar year of `occurred_at`, if it exists and is no longer in `DRAFT` status — that is, it has been compiled at least once — gets `totals_stale` true; and if that report's status is `PUBLISHED` or `REPUBLISHED`, it automatically transitions to `UNDER_AMENDMENT`.

The `FireSafetyReport` shell is created by a `SystemAdmin` for a unique `report_year` — duplicates yield `ERR_DUPLICATE_REPORT_YEAR` — and is born `DRAFT` with all totals zero and `totals_stale` false. Compilation by a `CleryCoordinator` is permitted from `DRAFT`, `COMPILED`, or `UNDER_AMENDMENT` and snapshots two deliberately divergent families of totals. Compiling from `DRAFT` or `COMPILED` leaves the report in `COMPILED` status; compiling during `UNDER_AMENDMENT` leaves the report in `UNDER_AMENDMENT` pending republication. The final family counts only incidents in `FINALIZED` status for the report year: `total_fires` is the count of such incidents, `total_injuries` and `total_deaths` are the sums of their `injuries` and `deaths`, and `total_damage_dollars` is the sum of their already-rounded `final_damage_dollars` values — round per incident, then sum, never round the sum. Incidents in `REPORTED` or `UNDER_ADJUSTMENT` contribute nothing to the final family. The provisional family is always computed alongside: `provisional_total_damage_dollars` sums the unrounded `estimated_damage_dollars` over the year's incidents currently in `REPORTED` status only, so the same incident population can contribute different totals to the two figures. A successful compile clears `totals_stale`.

Publication mirrors the ASR. A `PoliceChief` publishes a `COMPILED` report, stamping `published_at` and computing `is_late` under the same October 1 rule as the ASR. A coordinator may begin an amendment from `PUBLISHED` or `REPUBLISHED` (the cascade above can also force it), and republishing from `UNDER_AMENDMENT` — again the chief's publish action — additionally requires `totals_stale` to be false, meaning a fresh compile must have happened since the last fire-incident change; otherwise the publish is rejected with `ERR_INVALID_STATE`. Successful republication moves the report to `REPUBLISHED` and refreshes `published_at` and `is_late`.

### 3.9. Federal Program Reviews and Corrective Actions

A `FederalReviewer` opens a `ProgramReview` over a closed calendar-year interval from `scope_year_start` through `scope_year_end`, inclusive of both endpoints. The interval must not overlap any other review whose status is not `CLOSED`, and a shared boundary year counts as overlap — a review covering 2023–2024 and another covering 2024–2025 cannot coexist while either is open; violations are rejected with `ERR_REVIEW_SCOPE_OVERLAP` (HTTP 409). A new review is born `OPENED` with `penalty_score` 0, `escalated` false, `open_action_count` 0, and `opened_at` set to its creation time.

The review advances through `OPENED → FINDINGS_ISSUED → CORRECTIVE_ACTION → UNDER_VERIFICATION → CLOSED`, driven by the reviewer's advance call, with two gates enforced in order of the machine. Advancing from `FINDINGS_ISSUED` requires at least one corrective action to exist; advancing from `CORRECTIVE_ACTION` or from `UNDER_VERIFICATION` requires `open_action_count` to be zero. A gated advance that fails is rejected with `ERR_UNRESOLVED_ACTIONS` (HTTP 422). The arrival into `UNDER_VERIFICATION` can also happen automatically, as described below. From `UNDER_VERIFICATION` the reviewer may instead return the review to `CORRECTIVE_ACTION` via return-for-correction, optionally recording a `note`, which is stored on the review as `return_note`, forming a remediation loop. Closing a review has a lasting effect: its actions' `finding_code` values become visible to the repeat-finding detection of all later reviews.

Corrective actions are created by the reviewer while the review is `FINDINGS_ISSUED` or `CORRECTIVE_ACTION`, carrying `finding_code`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, a `description`, and a `due_date` no earlier than the date portion of the review's `opened_at`; each action's parent review is recorded as its `review_id`, and a new action is born `OPEN` with `resolution_summary` and `verification_note` null and `rejection_count` 0. Each action derives two scoring fields. `is_repeat_finding` is true when any corrective action with the same `finding_code` exists on any `CLOSED` review. `weight` is a base of 10 for `LOW`, 25 for `MEDIUM`, or 50 for `HIGH`, doubled when `is_repeat_finding` is true. Both fields are derived at read time, so one review closing retroactively updates the repeat-finding scoring of other reviews' actions. Creating an action increments the review's `open_action_count` by one and recomputes `penalty_score`, which is the sum of `weight` over all of the review's actions regardless of action status; `escalated` is true when `penalty_score` is at least 100 — exactly 100 escalates. A review's `open_action_count`, `penalty_score`, and `escalated` are likewise derived from its live action set on every read, `open_action_count` counting the actions in `OPEN` or `SUBMITTED` status.

Remediation is a dialogue. A `CleryCoordinator` submits an `OPEN` action with a `resolution_summary`, moving it `OPEN → SUBMITTED`; submission is only possible while the parent review is `CORRECTIVE_ACTION`, and otherwise fails with `ERR_INVALID_STATE`. The reviewer then verifies or rejects. Verification moves `SUBMITTED → VERIFIED` — the action's terminal state — decrements the review's `open_action_count` by one, and when that count reaches zero while the review is `CORRECTIVE_ACTION`, the review auto-advances to `UNDER_VERIFICATION`, recomputing `penalty_score` and `escalated` at the transition. Rejection moves `SUBMITTED → OPEN`, increments the action's `rejection_count` by one, stores the reviewer's `verification_note`, and leaves `open_action_count` unchanged on net, since both `SUBMITTED` and `OPEN` count as open.

---

## 4. Endpoint Definitions

All endpoints share the envelope, pagination, and error structure of §2. Creating a new resource returns HTTP 201 with the created resource; successful modifications, state transitions, and reads return HTTP 200 with the affected resource (or resource list). Error responses use the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the logical clock; before any call it reads exactly 2026-08-01T00:00:00Z | `SystemAdmin` |
| POST | `/clery-geographies` | Create a Clery geography zone | `SystemAdmin` |
| GET | `/clery-geographies` | List geographies with optional category/status filters | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/clery-geographies/{id}` | Get one geography | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| PATCH | `/clery-geographies/{id}` | Update or retire a geography; retirement blocked while referenced by non-terminal incidents or fire incidents | `SystemAdmin` |
| POST | `/campus-security-authorities` | Register a CSA | `SystemAdmin` |
| GET | `/campus-security-authorities` | List CSAs with optional filters | `SystemAdmin`, `CleryCoordinator`, `PoliceChief` |
| GET | `/campus-security-authorities/{id}` | Get one CSA; LAPSED evaluated lazily | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `CampusSecurityAuthority` |
| POST | `/campus-security-authorities/{id}/training-records` | Record CSA annual training; a passing score activates or re-certifies | `SystemAdmin` |
| GET | `/campus-security-authorities/{id}/training-records` | List training records of a CSA | `SystemAdmin`, `CleryCoordinator`, `PoliceChief` |
| POST | `/campus-security-authorities/{id}/deactivate` | Deactivate a CSA | `SystemAdmin` |
| POST | `/csa-referral-reports` | CSA files a crime referral report; `csa_id` taken from `X-User-ID` | `CampusSecurityAuthority` |
| GET | `/csa-referral-reports` | List referral reports; CSA callers see only their own | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `CampusSecurityAuthority` |
| GET | `/csa-referral-reports/{id}` | Get one referral report | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `CampusSecurityAuthority` |
| POST | `/csa-referral-reports/{id}/forward` | CSA forwards its own referral to campus police | `CampusSecurityAuthority` |
| POST | `/csa-referral-reports/{id}/mark-duplicate` | Mark a referral as a duplicate of an already-known incident | `CleryCoordinator` |
| POST | `/incident-reports` | Create an incident report in DRAFT; `referral_id` required iff `source` is CSA_REFERRAL and links that referral | `CleryCoordinator`, `PoliceChief` |
| GET | `/incident-reports` | List incidents with optional filters | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/incident-reports/{id}` | Get one incident | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/incident-reports/{id}/submit` | Submit a DRAFT incident; auto-creates its daily crime log entry | `CleryCoordinator`, `PoliceChief` |
| POST | `/incident-reports/{id}/begin-classification` | Move SUBMITTED to UNDER_CLASSIFICATION | `CleryCoordinator` |
| POST | `/incident-reports/{id}/classify` | Classify with an offense set (OCC on incident version); supersedes prior offense rows | `CleryCoordinator` |
| POST | `/incident-reports/{id}/begin-reclassification` | Move CLASSIFIED to UNDER_RECLASSIFICATION; blocked when the year's ASR is published | `CleryCoordinator` |
| POST | `/incident-reports/{id}/unfound` | Unfound an incident with justification; cascades to log entry and ASR staleness | `PoliceChief` |
| POST | `/incident-reports/{id}/withdraw` | Withdraw a DRAFT incident | `CleryCoordinator` |
| GET | `/incident-reports/{id}/offense-counts` | List the current offense rows of an incident | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/incident-reports/{id}/safety-alerts` | List the alerts of an incident | `SystemAdmin`, `CleryCoordinator`, `PoliceChief` |
| POST | `/incident-reports/{id}/safety-alerts` | Open a timely-warning / emergency-notification assessment for an incident | `CleryCoordinator` |
| GET | `/safety-alerts/{id}` | Get one alert | `SystemAdmin`, `CleryCoordinator`, `PoliceChief` |
| POST | `/safety-alerts/{id}/decide` | Decide ISSUE or NO_ISSUE | `CleryCoordinator` |
| POST | `/safety-alerts/{id}/authorize` | Authorize dissemination (segregation of duties) | `PoliceChief` |
| POST | `/safety-alerts/{id}/disseminate` | Disseminate via channels | `PoliceChief` |
| POST | `/safety-alerts/{id}/close` | Close a disseminated or no-issue alert | `CleryCoordinator` |
| POST | `/safety-alerts/{id}/reopen` | Reopen a closed alert within 72 hours | `CleryCoordinator` |
| GET | `/daily-crime-log` | Public crime log; Anonymous sees only public entries; staff may pass `include_unfounded` | `Anonymous`, `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/daily-crime-log/{id}` | Get one log entry | `Anonymous`, `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| PATCH | `/daily-crime-log-entries/{id}/disposition` | Change disposition; UNFOUNDED not allowed here (cascade-only) | `PoliceChief` |
| POST | `/daily-crime-log/inspection-requests` | Public request for log inspection; immediate fulfillment when the window is within 60 days | `Anonymous` |
| GET | `/log-inspection-requests/{id}` | Get one inspection request | `Anonymous`, `CleryCoordinator`, `PoliceChief` |
| POST | `/log-inspection-requests/{id}/fulfill` | Fulfill a pending inspection request | `CleryCoordinator` |
| POST | `/annual-security-reports` | Create an ASR shell for a report year | `SystemAdmin` |
| GET | `/annual-security-reports` | List ASRs with optional filters | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/annual-security-reports/{id}` | Get one ASR | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/annual-security-reports/{id}/compile` | Compile a statistics snapshot (OCC on report version); allowed in COLLECTING and UNDER_AMENDMENT | `CleryCoordinator` |
| GET | `/annual-security-reports/{id}/statistic-lines` | List statistic lines (default CURRENT snapshot) | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/annual-security-reports/{id}/submit-review` | Move COLLECTING to UNDER_REVIEW; requires a prior FINAL compile | `CleryCoordinator` |
| POST | `/annual-security-reports/{id}/publish` | Move UNDER_REVIEW to PUBLISHED; sets `is_late` | `PoliceChief` |
| POST | `/annual-security-reports/{id}/begin-amendment` | Move PUBLISHED/REPUBLISHED to UNDER_AMENDMENT | `CleryCoordinator` |
| POST | `/annual-security-reports/{id}/republish` | Move UNDER_AMENDMENT to REPUBLISHED; requires a recompile after amendment start | `PoliceChief` |
| POST | `/fire-incidents` | Report a fire in an on-campus residential facility | `CleryCoordinator`, `PoliceChief` |
| GET | `/fire-incidents` | List fire incidents with optional filters | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/fire-incidents/{id}` | Get one fire incident | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/fire-incidents/{id}/finalize` | Finalize adjudicated damage (rounded half up to whole dollars) | `PoliceChief` |
| POST | `/fire-incidents/{id}/begin-adjustment` | Move FINALIZED to UNDER_ADJUSTMENT | `PoliceChief` |
| POST | `/fire-safety-reports` | Create a fire safety report shell for a year | `SystemAdmin` |
| GET | `/fire-safety-reports` | List fire safety reports | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/fire-safety-reports/{id}` | Get one fire safety report | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/fire-safety-reports/{id}/compile` | Snapshot fire statistics | `CleryCoordinator` |
| POST | `/fire-safety-reports/{id}/publish` | Move COMPILED to PUBLISHED, or UNDER_AMENDMENT to REPUBLISHED | `PoliceChief` |
| POST | `/fire-safety-reports/{id}/begin-amendment` | Move PUBLISHED/REPUBLISHED to UNDER_AMENDMENT | `CleryCoordinator` |
| POST | `/program-reviews` | Open a federal program review over a closed year interval | `FederalReviewer` |
| GET | `/program-reviews` | List program reviews | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| GET | `/program-reviews/{id}` | Get one program review | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/program-reviews/{id}/advance` | Advance the review one stage; gates enforced per state machine | `FederalReviewer` |
| POST | `/program-reviews/{id}/return-for-correction` | Loop UNDER_VERIFICATION back to CORRECTIVE_ACTION | `FederalReviewer` |
| POST | `/program-reviews/{id}/corrective-actions` | Add a corrective action; allowed in FINDINGS_ISSUED and CORRECTIVE_ACTION | `FederalReviewer` |
| GET | `/program-reviews/{id}/corrective-actions` | List corrective actions of a review | `SystemAdmin`, `CleryCoordinator`, `PoliceChief`, `FederalReviewer` |
| POST | `/corrective-actions/{id}/submit` | Submit remediation evidence; requires the review in CORRECTIVE_ACTION | `CleryCoordinator` |
| POST | `/corrective-actions/{id}/verify` | Verify a submitted action; the last verification auto-advances the review | `FederalReviewer` |
| POST | `/corrective-actions/{id}/reject` | Reject a submitted action back to OPEN | `FederalReviewer` |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INCIDENT_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_FAILED` | 422 |
| `ERR_UNFOUNDED_JUSTIFICATION_REQUIRED` | 422 |
| `ERR_CSA_NOT_CERTIFIED` | 422 |
| `ERR_CLASSIFICATION_INCOMPLETE` | 422 |
| `ERR_REPORT_LOCKED` | 409 |
| `ERR_ALERT_WINDOW_EXPIRED` | 422 |
| `ERR_DUPLICATE_REPORT_YEAR` | 409 |
| `ERR_REVIEW_SCOPE_OVERLAP` | 409 |
| `ERR_TRAINING_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_ACTIVE_ALERT` | 409 |
| `ERR_GEOGRAPHY_RETIRED` | 422 |
| `ERR_GEOGRAPHY_IN_USE` | 409 |
| `ERR_RESIDENTIAL_FACILITY_REQUIRED` | 422 |
| `ERR_NO_DISTRIBUTION_CHANNELS` | 422 |
| `ERR_FINAL_COMPILE_REQUIRED` | 422 |
| `ERR_RECOMPILE_REQUIRED` | 422 |
| `ERR_UNRESOLVED_ACTIONS` | 422 |
| `ERR_ENTRY_NOT_PUBLIC` | 403 |

# Government Cloud Authorization Program API — Product Requirements Document

## 1. Introduction

Federal agencies buy cloud services on the strength of a security authorization that somebody else paid for. The Government Cloud Authorization Program exists to make that authorization trustworthy and reusable: a cloud service provider categorizes the information its offering will hold, implements a control baseline sized to that categorization, hires an accredited assessment organization to test the result, works down the findings that testing produces, and finally hands a complete authorization package to whoever is willing to accept the residual risk — either a single sponsoring agency or the program board itself. Once the authorization letter is issued, the offering does not stop being watched; it submits vulnerability scans every month, files significant change requests before it touches its boundary, and answers for every finding that slips past its remediation deadline.

This API is the system of record for that entire arc. It is deliberately unforgiving about ordering and evidence: an offering cannot select an authorization path before its impact level is determined, a package cannot be submitted before the assessment report is delivered, a deviation cannot be decided by the same board member who routed it, and a reuse grant cannot be created against an authorization whose posture has escalated. Three parties with genuinely different incentives — the provider's compliance team, the independent assessor, and the government reviewers — write into the same records, so the API also has to be explicit about who owns which identity, which decisions are segregated, and how two writers competing over the same parent record are told apart.

The requirements below are organized so that the global contract (authentication, envelope shape, pagination, precision, concurrency, cascade behaviour) is stated once in §2, and the domain workflows that use it — categorization, assessment, plan-of-action management, package review, continuous monitoring, change control and agency reuse — are described in §2's terms in §3. §4 and §5 supply the HTTP surface and the error inventory. Time in this system is a *logical clock*, not wall-clock time; §2.5 defines it, and every deadline, window, timeliness and expiry comparison in the document reads from it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that hold for every endpoint, every resource and every workflow described later.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the four roles the program recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (401). The four roles are `CspComplianceLead`, `ThirdPartyAssessor`, `AgencyAuthorizingOfficial` and `ProgramBoardReviewer`. When the acting role is not listed as authorized for the endpoint being called (see §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (403). All read endpoints in §4 are open to all four roles, with the single exception described at the end of this subsection.

The four roles bind `X-User-ID` to resources differently, and the difference matters for every ownership check in the document:

- When `X-User-Role` is `CspComplianceLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `owner_user_id` on the `CloudServiceOffering` the lead creates, as `submitted_by_user_id` on a `DeviationRequest`, and as `submitted_by_user_id` on a `ScanSubmission`, but it never compares it to any entity's `id`. Every provider-side mutation on an offering, and on the control implementations, engagements, findings, packages, scan submissions, change requests and package-access grants that hang off it, requires the acting `X-User-ID` to equal that offering's `owner_user_id`.
- When `X-User-Role` is `ThirdPartyAssessor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It is compared against `assessor_user_id` on the `AssessmentEngagement` being acted upon, and never against an entity's `id`.
- When `X-User-Role` is `AgencyAuthorizingOfficial`, `X-User-ID` is the `id` of the acting `Agency`; ownership checks on any resource that references an `Agency` compare the resource's foreign-key field to `X-User-ID`. Concretely, sponsorship checks compare it to the offering's `sponsor_agency_id` and reuse-grant ownership checks compare it to the grant's `agency_id`.
- When `X-User-Role` is `ProgramBoardReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `reviewed_by_user_id` on an `AuthorizationPackage` taken into review and as `routed_by_user_id` on a routed `DeviationRequest`, and compares it against those recorded values for segregation of duties (§2.8), but never against any entity's `id`.

Any ownership failure of the three kinds above — a lead who is not the offering owner, an assessor who is not the engagement's assessor, or an agency official who is not the grant's agency — is rejected with `ERR_NOT_RESOURCE_OWNER` (403). An `AgencyAuthorizingOfficial` who acts on a decision reserved for the offering's sponsoring agency without being that sponsor is rejected with `ERR_SPONSOR_AGENCY_MISMATCH` (403).

Two further access rules sit at role level. First, some endpoints accept more than one role but discriminate on the requested action or the routed queue: an attempt by the wrong role to perform a specific action is rejected with `ERR_ACTION_ROLE_MISMATCH` (403), and an attempt by the wrong role to act on a queue-owned or path-owned decision is rejected with `ERR_WRONG_REVIEW_QUEUE` (403). Second, reading an authorization package is the one read in the system that is not universally open: an `AgencyAuthorizingOfficial` may read a package only if that official's agency is the offering's sponsor, or if the official's agency holds a reuse grant on the resulting authorization whose `access_state` is one of `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW`, `REUSE_ACCEPTED` or `NOTICE_ISSUED`. Otherwise the read is refused with `ERR_PACKAGE_ACCESS_DENIED` (403). The other three roles read packages without restriction.

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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0. A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (400).

Unless a specific endpoint states otherwise, every list endpoint returns its rows ordered by `created_at` ascending. List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied.

### 2.4. Record Identity and Audit Fields

Every resource in the system carries a server-minted `id`, formatted as a UUID with no type prefix of any kind. Clients never supply an `id`.

Most resources additionally carry the full audit triplet:

- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row.
- `version` (integer): starts at 1 and increments by one on every mutation of the row.

Two resource types are exceptions and carry only `id` and `created_at`: a `ControlBaseline`, which is published once and never edited, and a `ScanSubmission`, which is an immutable append-only record of one monthly scan delivery. Neither of these two carries `updated_at` and neither carries `version` — those fields are absent from their responses entirely.

A refresh of a derived field counts as a mutation. When the server recomputes an offering's impact levels, an engagement's hour ledger, an authorization's finding counters or risk score, or a monitoring period's submission counters, the affected row's `updated_at` is refreshed and its `version` increments — even though no client field was written directly. The version-increment side effects named throughout §3 are therefore statements about which rows a single request touches, and each named increment is one increment of one.

### 2.5. The Logical Clock

All time-sensitive behaviour in this system reads from a server-held **logical clock** rather than from real wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any client moves it, that default is what every comparison sees, and the server never falls back to real time. A `ProgramBoardReviewer` may move the clock by supplying a `to_iso8601` instant; the response reports the new setting as `current_utc`.

Everything that compares instants uses this clock: remediation deadline evaluation, assessment-plan and test-slot windows, change-window separation, scan timeliness, monitoring-period opening and closing, authorization expiry, and the `submitted_at` / `authorized_at` / `closed_at` / `reuse_accepted_at` stamps the server writes.

### 2.6. Path Resolution and Foreign-Key Integrity

When a request path contains more than one identifier, the identifiers are resolved strictly left to right, and the first one that does not resolve determines the error. A request that targets a monitoring period's scan submissions under a monitoring period that does not exist therefore fails with `ERR_MONITORING_PERIOD_NOT_FOUND` before anything else about the request is examined.

Foreign keys carried in a request body are resolved after path identifiers, in the order in which the endpoint declares its input fields. Each unresolvable reference raises the 404 error belonging to the referenced type: `ERR_OFFERING_NOT_FOUND`, `ERR_DATA_CATEGORY_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`, `ERR_CONTROL_IMPLEMENTATION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_TEST_SLOT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_POAM_ITEM_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_MONITORING_PERIOD_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_REUSE_GRANT_NOT_FOUND` or `ERR_AGENCY_NOT_FOUND`. An unresolvable `supersedes_item_id` on a new finding raises `ERR_POAM_ITEM_NOT_FOUND`.

The same discipline applies to the foreign-key *filters* of the offering list read. Filtering offerings by a `baseline_id` that names no baseline fails with `ERR_BASELINE_NOT_FOUND`, and filtering by a `sponsor_agency_id` that names no agency fails with `ERR_AGENCY_NOT_FOUND`. These two filters 404 rather than returning an empty page. The non-foreign-key filters of that same read — `status` and `authorization_path` — behave normally and simply narrow the result set.

### 2.7. Validation Precedence

Many endpoints in this system can fail for several reasons at once, and the benchmark for correctness is *which* reason is reported. Checks are therefore evaluated in one fixed global order, and the first failing check determines the response. Lower-numbered tiers are evaluated first:

1. Header presence and role legality — `ERR_UNAUTHENTICATED`.
2. The acting role appears in the endpoint's authorized-role list — `ERR_FORBIDDEN_ROLE`.
3. The requested action is permitted for the acting role on the remediation endpoint — `ERR_ACTION_ROLE_MISMATCH`.
4. The acting role owns the queue or path that owns the decision — `ERR_WRONG_REVIEW_QUEUE`. This tier guards deviation routing, deviation decisions, package decisions, change-request decisions and assessment-plan approvals.
5. Request shape: required fields present, enum members legal, numbers positive where the field demands it, arrays non-empty and duplicate-free (with the single exception of the assessment report's `findings` array, which may legally be empty), `period_month` well formed, pagination inside its bounds — `ERR_INVALID_REQUEST`.
6. Every identifier in the request path exists, resolved left to right — the corresponding 404.
7. Every foreign key in the request body resolves, in the endpoint's declared field order, as do the two foreign-key filters of the offering list read — the corresponding 404.
8. The acting identity owns the target row — `ERR_NOT_RESOURCE_OWNER`.
9. Agency access to a package read is backed by sponsorship or an access-bearing reuse grant — `ERR_PACKAGE_ACCESS_DENIED`.
10. The supplied parent version matches the parent's current `version` — `ERR_STALE_OFFERING_VERSION` or `ERR_STALE_AUTHORIZATION_VERSION` (412), per §2.10.
11. The target row currently sits in a state the requested transition declares as a from-state — `ERR_INVALID_STATE` (409).
12. The target row is not already in a terminal state for the requested transition — `ERR_ALREADY_TERMINAL` (409). This tier guards exactly five operations: cancelling a test slot, closing a monitoring period, revoking a reuse grant, the supersession target of a new finding, and filing a deviation request. On those five, a target that is already terminal is reported here rather than at tier 11, so the two never both fire.
13. The package's backing engagement has delivered its report — `ERR_ENGAGEMENT_REPORT_NOT_DELIVERED` (409).
14. The authorization is in `authorization_status` `AUTHORIZED` and its `monitoring_posture` is not `ESCALATED` — `ERR_AUTHORIZATION_NOT_ACTIVE` (409). This gate guards reuse-grant creation, incremental review, and opening a monitoring period.
15. The finding carries no deviation request still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW` — `ERR_DEVIATION_PENDING_ON_ITEM` (409), on verification closure.
16. An inherited control's source offering is in status `AUTHORIZED` — `ERR_INHERITED_OFFERING_NOT_AUTHORIZED` (409), on control-implementation creation and update.
17. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (409), on deviation decisions and package decisions.
18. At least one data category of the offering is `CONFIRMED` — `ERR_NO_CONFIRMED_DATA_CATEGORY` (422).
19. A non-retired baseline exists for the determined final impact level — `ERR_BASELINE_NOT_AVAILABLE` (422).
20. `customer_responsibility_text` is present and non-empty whenever `crm_documented` is true — `ERR_CRM_TEXT_REQUIRED` (422).
21. `scan_types` contains all three mandatory scan types — `ERR_INCOMPLETE_SCAN_SET` (422).
22. Interval sanity: a start strictly precedes its end, for test slots, change windows and assessment plans — `ERR_WINDOW_INVALID` (422).
23. `detected_at` is not after the logical clock — `ERR_DETECTION_DATE_IN_FUTURE` (422), on finding creation and on report delivery.
24. The logical clock is at or after the monitoring period's `window_start` — `ERR_SCAN_WINDOW_NOT_OPEN` (422).
25. The logical clock is at or after the monitoring period's `window_end` — `ERR_PERIOD_NOT_ENDED` (409), on period closure.
26. Test-slot interval overlap — `ERR_TEST_SLOT_OVERLAP` (409).
27. Change-window separation — `ERR_CHANGE_WINDOW_BUFFER_VIOLATION` (409).
28. `period_month` is unique per authorization — `ERR_DUPLICATE_MONITORING_PERIOD` (409).
29. No live reuse grant already pairs this authorization with this agency — `ERR_DUPLICATE_REUSE_GRANT` (409).
30. `control_id` is unique per offering and `category_code` is unique per offering — `ERR_DUPLICATE_CONTROL_IMPLEMENTATION` (409).
31. The offering holds fewer than three authorization packages in total — `ERR_REVISION_LIMIT_EXCEEDED` (409).
32. The engagement named by a new package belongs to the same offering — `ERR_ENGAGEMENT_OFFERING_MISMATCH` (409).
33. The deviation's finding belongs to an offering the acting official is entitled to act on — `ERR_POAM_OFFERING_MISMATCH` (409), on deviation filing and deviation decisions.
34. The acting `AgencyAuthorizingOfficial` is the offering's sponsor — `ERR_SPONSOR_AGENCY_MISMATCH` (403), on package decisions, plan approvals, change-request decisions and deviation decisions.
35. `supersedes_item_id` points at a finding of the same offering — `ERR_SUPERSEDED_ITEM_MISMATCH` (409).
36. Customer-responsibility-matrix coverage is sufficient at submission — `ERR_CRM_COVERAGE_INSUFFICIENT` (422).
37. Submission-time residual risk is below its ceiling — `ERR_RESIDUAL_RISK_TOO_HIGH` (422).
38. No open high-severity finding is past its deadline at submission — `ERR_OVERDUE_HIGH_FINDINGS` (422).
39. Requested slot hours fit the engagement's unallocated pool — `ERR_ENGAGEMENT_HOURS_EXHAUSTED` (422).
40. The authorization has a free reuse seat — `ERR_REUSE_SEATS_EXHAUSTED` (422).
41. The sponsoring agency has sponsorship capacity left — `ERR_SPONSORSHIP_CAPACITY_EXCEEDED` (422).
42. An incremental-review acceptance is within the findings tolerance — `ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE` (422).
43. The engagement's total cost fits the offering's approved assessment budget — `ERR_ASSESSMENT_BUDGET_EXCEEDED` (422).

Two consequences of this ordering are worth calling out because they are easy to get backwards. Ownership (tier 8) is checked before any state or version check, so a non-owner acting on a row in the wrong state is told they are not the owner. And the entitlement check at tier 33 precedes the sponsor check at tier 34: an agency official who decides a deviation on a finding belonging to an offering they have no relationship with is refused with `ERR_POAM_OFFERING_MISMATCH`, because the finding's offering is not one that official may act on at all, before the sponsor comparison is ever reached.

### 2.8. Segregation of Duties Across the Review Queues

The program board is not permitted to mark its own homework, and two specific pairs of actions are held apart by identity. The board member who routes a deviation request into a review queue may not be the board member who decides it: on a deviation decision the acting `X-User-ID` must differ from the request's recorded `routed_by_user_id`, and an equal value is refused with `ERR_SEGREGATION_OF_DUTIES` (409). Likewise, the board member who performs the completeness review of an authorization package may not issue the program-board authorization decision for it: on a `PROGRAM_BOARD` package decision the acting `X-User-ID` must differ from the package's recorded `reviewed_by_user_id`, and an equal value is refused with the same error. Segregation of duties is a program-board concern; it does not constrain an `AgencyAuthorizingOfficial`, whose decisions are instead constrained by the sponsorship and entitlement checks of §2.1 and §2.7.

Queue ownership is enforced alongside it. A deviation routed to the board queue may only be decided by a `ProgramBoardReviewer`; a deviation routed to the agency queue may only be decided by an `AgencyAuthorizingOfficial`; and on the `PROGRAM_BOARD` authorization path, package decisions and significant-change decisions belong to a `ProgramBoardReviewer` while on the `AGENCY_SPONSORED` path they belong to the sponsoring agency's official. Every violation of queue or path ownership, including routing a deviation into a queue that is illegal for its `kind`, raises `ERR_WRONG_REVIEW_QUEUE` (403).

### 2.9. Numeric Precision and Rounding

Every monetary amount, hour figure, percentage and risk score the system computes is rounded to exactly two decimal places using the round-half-up method, and is returned in responses as a JSON number rather than a string. Where a formula in §3 applies rounding more than once — the coverage percentage and the residual risk score both do — the order of the rounding steps is part of the specification and is stated with the formula; applying the roundings in a different order produces a different, wrong figure.

Two families of quantities are not decimal. Day counts, extension grants, lateness figures and every counter (`submission_round`, `notice_count`, `reopen_count`, `accepted_submission_count`, `boundary_version`, and the rest) are whole integers. Instants are exact ISO 8601 UTC timestamps, and comparisons on them are made on the full timestamp, not on a truncated date: separation and adjacency rules in §3 that speak of "at least 7 days" or "at or after" mean exactly that on the full instant, so a gap of six days and 23 hours 59 minutes 59 seconds does not satisfy a seven-day requirement.

### 2.10. Optimistic Concurrency Control

Two write operations in this system take a parent record's version as a mandatory input, because both of them silently invalidate work the client may not have observed.

Creating an authorization package at `POST /authorization-packages` requires `expected_offering_version` — not optional — carrying the client's last observed `version` of the target `CloudServiceOffering`. If that value does not equal the offering's current `version`, the create is rejected with `ERR_STALE_OFFERING_VERSION` (412). The protection matters because a newly created package legitimately supersedes any `DRAFT` or `REVISION_REQUESTED` package of the same offering; a creation carrying a stale expected version would discard a package the client never saw, and the version check turns that into a deterministic refusal instead.

Creating a reuse grant at `POST /reuse-grants` requires `expected_authorization_version` — again not optional — carrying the client's last observed `version` of the target `Authorization`. A mismatch with the authorization's current `version` is rejected with `ERR_STALE_AUTHORIZATION_VERSION` (412). Here the reason is the finite seat pool: each grant consumes one seat, a grant for a different agency would otherwise succeed against identical state, so the seat count the client based its request on must still be current.

No other endpoint takes a version field. Endpoints not named in this subsection perform no version comparison, and supplying one to them has no effect.

### 2.11. Cascades, Counter Reconciliation and Conservation Invariants

A single request in this system routinely mutates several rows. The offering is the hub: confirming or withdrawing a data category, determining the impact level, selecting the path, approving an assessment plan, submitting a package, deciding a package, filing a change request and deciding a change request each increment the offering's `version` by one in addition to whatever they write on their own resource. Where §3 describes a chain — a package decision creating an authorization, that authorization creating the first monitoring period; a deficient period close incrementing a run counter, that counter moving the monitoring posture, that posture issuing reuse notices, those notices incrementing an agency counter — every link fires within the one request, not lazily and not on a subsequent read.

Three conservation invariants hold at all times and are the reason certain operations are described as compensating rather than merely reversing:

- **Assessment hour conservation.** An engagement's `contracted_hours` always equals its `allocated_hours` plus its `unallocated_hours`. Cancelling a test slot returns that slot's hours to the unallocated pool and removes them from the allocated total, restoring the identity exactly.
- **Reuse seat conservation.** An authorization's `reuse_seats_total` always equals its `reuse_seats_granted` plus its `reuse_seats_available`. Revoking a grant returns its seat: granted decreases by one and available increases by one.
- **Finding status partition conservation.** For any offering, `total_findings_count` on its authorization always equals `open_findings_count` plus `closed_findings_count`. Reopening a closed finding moves one unit from the closed side to the open side, and the residual risk score is recomputed in the same request.

Counters that count rows are maintained by the mutations that change their underlying populations, as described in §3, and are always readable at their reconciled values. Each one has an exact population, and the increments and decrements in §3 exist only to keep the counter equal to it:

- An agency's `sponsored_offering_count` counts the offerings whose `sponsor_agency_id` is that agency; its `reuse_grant_count` counts that agency's reuse grants whose `access_state` is not `REVOKED`; its `open_notice_count` counts that agency's grants currently in `access_state` `NOTICE_ISSUED`.
- An offering's `open_package_count` counts its authorization packages in `status` `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED`; its `superseded_package_count` counts its packages in `status` `SUPERSEDED`; its `included_service_count` counts the services inside the authorization boundary.
- A period's `accepted_submission_count`, `late_submission_count` and `rejected_submission_count` count its scan submissions whose `status` is `ACCEPTED`, `LATE_ACCEPTED` and `REJECTED` respectively.
- An authorization's `total_findings_count` counts all findings of its offering; `open_findings_count` counts those whose `remediation_status` is not `CLOSED`; `closed_findings_count` counts those whose `remediation_status` is `CLOSED`; `risk_accepted_findings_count` counts those whose `risk_disposition` is `RISK_ACCEPTED`. Its `reuse_seats_granted` counts the authorization's grants whose `access_state` is not `REVOKED`, and `reuse_seats_available` is `reuse_seats_total` less that count.

### 2.12. Rows With Two Independent Status Dimensions

Two resource types carry two orthogonal state dimensions on a single row, and a transition in one dimension never implies a transition in the other unless §3 explicitly says so.

A `PoamItem` carries `remediation_status`, whose values are `OPEN`, `IN_REMEDIATION`, `AWAITING_VERIFICATION` and `CLOSED`, alongside `risk_disposition`, whose values are `NONE`, `DEVIATION_REQUESTED`, `EXTENSION_GRANTED`, `RISK_ACCEPTED` and `FALSE_POSITIVE_ACCEPTED`. Starting remediation work moves only the remediation dimension; filing a deviation moves only the risk dimension. There is exactly one crossing: an approved false-positive deviation moves the risk dimension to `FALSE_POSITIVE_ACCEPTED` *and* drives the remediation dimension to `CLOSED`.

An `Authorization` carries `authorization_status`, whose values are `AUTHORIZED`, `SUSPENDED`, `REVOKED` and `EXPIRED`, alongside `monitoring_posture`, whose values are `ACTIVE`, `AT_RISK` and `ESCALATED`. A first deficient monitoring month moves the posture without touching the authorization status; a second one moves both. `REVOKED` and `EXPIRED` are terminal for the authorization dimension.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Program: Agencies and Control Baselines

Before any offering can be authorized, the program board populates two reference registries. Registering a federal agency records its display `name` and its `agency_code`, a short code of two to eight uppercase letters that must be unique across all agencies. An agency's `status` is either `ACTIVE` or `INACTIVE` and defaults to `ACTIVE`; only an `ACTIVE` agency may take on a new sponsorship. Sponsorship is deliberately rationed: `sponsorship_capacity` is a non-negative integer, defaulting to 3, that caps how many offerings the agency may sponsor at one time, and it is compared against the system-maintained `sponsored_offering_count`, which counts the offerings naming this agency as sponsor. Two further system counters ride on the agency row for the reuse programme: `reuse_grant_count`, the number of this agency's reuse grants not in the revoked state, and `open_notice_count`, the number of its grants currently sitting under an issued notice. All three counters start at 0.

A **control baseline** is the requirement set an offering must implement, published once per impact level and never edited afterwards. Publishing one records the `impact_level` it applies to — `LOW`, `MODERATE` or `HIGH` — a human-readable `version_label` such as REV5-MOD, an `effective_from` instant from which it becomes the selectable baseline for its impact level, and a `retired` flag defaulting to false that excludes it from selection when set. The substance of the baseline is its `families` array, which must be non-empty and whose elements each carry a `family_code` (unique within the one baseline), a `required_control_count` of zero or more, and a `priority_rank` of one or more. On publication the server computes `total_required_controls` as the sum of the `required_control_count` values across all families. Baselines are the only reference data in the system that never changes after creation, which is why (per §2.4) a baseline row carries `id` and `created_at` and nothing else.

### 3.2. Offering Intake, Data Categorization and Impact Determination

A `CspComplianceLead` opens the process by registering a **cloud service offering**, supplying its `name`, the `provider_name` of the operating organization, a `service_model` of `IAAS`, `PAAS` or `SAAS`, a `deployment_model` of `GOV_COMMUNITY`, `PUBLIC`, `HYBRID` or `PRIVATE`, and an `assessment_budget_usd` — the finance-approved spend authorization for third-party assessment, which must be greater than zero and is held to two decimal places. Optionally the lead declares `external_dependency_impact_level`, the highest impact level of the external systems the offering leans on; it defaults to `LOW`. The server stamps `owner_user_id` from the acting `X-User-ID` and places the offering in status `DRAFT`. A fresh offering has `authorization_path`, `sponsor_agency_id`, `baseline_id`, `preliminary_impact_level` and `final_impact_level` all null, `boundary_version` at 1, and `included_service_count`, `open_package_count` and `superseded_package_count` all at 0.

While the offering is `DRAFT`, the lead declares the information types inside its boundary. Each **data category** records a `category_code` such as PII or FINANCIAL, unique among the offering's categories, together with three FIPS-199 ratings — `confidentiality_impact`, `integrity_impact` and `availability_impact`, each `LOW`, `MODERATE` or `HIGH`. The server attaches `offering_id` from the creation path, sets the category's `status` to `DECLARED`, and leaves `confirmed_by_user_id` null. A second category re-using an existing `category_code` on the same offering is refused with `ERR_DUPLICATE_CONTROL_IMPLEMENTATION`.

Categorization review is a government act. A `ProgramBoardReviewer` or an `AgencyAuthorizingOfficial` reviews a `DECLARED` category with a `decision` of either `CONFIRM`, which moves it `DECLARED → CONFIRMED`, or `WITHDRAW`, which moves it `DECLARED → WITHDRAWN`. Both legs require the category to still be `DECLARED` and the parent offering to still be in `DRAFT`, both write `confirmed_by_user_id` from the reviewer's `X-User-ID`, and both recompute the offering's `preliminary_impact_level` and increment the offering's `version` by one. `WITHDRAWN` is terminal for a category, and a withdrawn category is invisible to every impact computation thereafter.

The **preliminary impact level** is a high-water mark maintained continuously while the offering is `DRAFT`, and it is recomputed on every data-category creation, confirmation and withdrawal. Rank the three levels so that `LOW` is 1, `MODERATE` is 2 and `HIGH` is 3. Consider every data category of the offering whose `status` is `DECLARED` or `CONFIRMED`; withdrawn categories are excluded. For each such category take the highest rank among its confidentiality, integrity and availability ratings, then take the greatest of those per-category highs across the set: `preliminary_impact_level` is the level with that rank. When no category qualifies, `preliminary_impact_level` is null. This variant deliberately treats a merely declared category as if it were already confirmed, and it ignores `external_dependency_impact_level` entirely — so the preliminary figure can sit strictly above the level the offering ultimately lands on.

Impact determination is the gate out of `DRAFT` and is reserved to a `ProgramBoardReviewer`. It computes the **final impact level** over `CONFIRMED` categories only. If the offering has no confirmed category at all, the request fails with `ERR_NO_CONFIRMED_DATA_CATEGORY`. Otherwise take the highest of the three ratings for each confirmed category, take the greatest of those per-category highs as a water mark, and then compare that water mark's rank against the rank of the offering's `external_dependency_impact_level`: `final_impact_level` is the level whose rank is the greater of the two. An unconfirmed `HIGH` category therefore does not raise the final level, while a `HIGH` external dependency does.

The same request binds the baseline. Candidates are the control baselines whose `impact_level` equals the determined final level and whose `retired` flag is false; if that candidate set is empty the request fails with `ERR_BASELINE_NOT_AVAILABLE`. From the candidates the server selects the one with the greatest `effective_from`, breaking a tie in favour of the smallest `created_at`, and writes its identifier into the offering's `baseline_id`. On success the offering moves `DRAFT → CATEGORIZED`, `final_impact_level` and `baseline_id` are written, and the offering's `version` increments by one. The transition requires the offering to be in `DRAFT`; an offering in any other status is refused with `ERR_INVALID_STATE`.

Offerings can be listed with filters on `status`, `authorization_path`, `baseline_id` and `sponsor_agency_id` alongside the standard `limit` and `offset`, and read individually with their computed impact levels and package counters exposed.

### 3.3. Choosing the Authorization Path

With the offering `CATEGORIZED`, its owning `CspComplianceLead` selects the `authorization_path`, which is either `AGENCY_SPONSORED` or `PROGRAM_BOARD` and which decides for the rest of the offering's life who is entitled to approve its assessment plan, accept its residual risk and decide its significant changes. Path selection moves the offering `CATEGORIZED → PATH_SELECTED` and increments its `version` by one; attempting it from any other status is refused with `ERR_INVALID_STATE`.

The two branches carry mirror-image requirements on the same payload. On the `AGENCY_SPONSORED` branch a `sponsor_agency_id` must be supplied, that agency's `status` must be `ACTIVE`, and its `sponsored_offering_count` must be strictly less than its `sponsorship_capacity`; an agency already sponsoring as many offerings as its capacity allows causes the selection to fail with `ERR_SPONSORSHIP_CAPACITY_EXCEEDED`. On success the server writes both `authorization_path` and `sponsor_agency_id` onto the offering, increments the sponsoring agency's `sponsored_offering_count` by one, and increments that agency's `version` by one. On the `PROGRAM_BOARD` branch `sponsor_agency_id` must be absent; supplying one is a malformed request and is refused with `ERR_INVALID_REQUEST`. In that case the server writes `authorization_path` as `PROGRAM_BOARD` and leaves `sponsor_agency_id` null, and no agency row is touched.

### 3.4. Control Implementation and the Customer Responsibility Matrix

Against the bound baseline, the compliance lead records one **control implementation** per control. Each carries the `offering_id` of the offering implementing it, a `control_id` such as AC-2 that must be unique among that offering's implementations, and a `family_code` that must match one of the `family_code` values in the offering's selected baseline. Its `implementation_status` is one of `IMPLEMENTED`, `PARTIALLY_IMPLEMENTED`, `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE`, defaulting to `PLANNED`. A duplicate `control_id` on the same offering is refused with `ERR_DUPLICATE_CONTROL_IMPLEMENTATION`.

Controls may be inherited rather than implemented directly. Supplying `inherited_from_offering_id` names the already-authorized offering the control is inherited from; leaving it null (the default) marks the control as directly implemented. Inheritance is only legal from an offering whose `status` is `AUTHORIZED`; pointing at an offering in any other status is refused with `ERR_INHERITED_OFFERING_NOT_AUTHORIZED`, both when the implementation row is created and when it is later updated.

The customer responsibility matrix is documented on the same row. `crm_documented` is a boolean defaulting to false that asserts the matrix entry for this control has been written, and `customer_responsibility_text` holds the matrix prose, defaulting to null. The two are coupled: whenever `crm_documented` is true, `customer_responsibility_text` must be present and non-empty, and a violation is refused with `ERR_CRM_TEXT_REQUIRED` on both creation and update. Updating an implementation may revise `implementation_status`, `crm_documented`, `customer_responsibility_text` or `inherited_from_offering_id`, and increments the row's own `version` by one. Implementations are listed with filters on `offering_id`, `inherited_from_offering_id`, `family_code`, `implementation_status` and `crm_documented`.

**Coverage** is the number the program actually cares about, and it is computed rather than stored — available as a live computed read, and frozen onto a package at submission. The computation walks the families of the offering's bound baseline in ascending `priority_rank`, breaking ties by `family_code` in ascending alphabetical order. A family whose `required_control_count` is zero is skipped entirely: it contributes to neither the numerator nor the weight. For each remaining family, count the offering's control implementations whose `family_code` matches that family, whose `implementation_status` is either `IMPLEMENTED` or `PARTIALLY_IMPLEMENTED`, and whose `crm_documented` is true — implementations that are `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE` never count, and neither does an implementation whose matrix entry is undocumented. Take the lesser of that count and the family's `required_control_count`, divide it by `required_control_count`, multiply by 100, and round half up to two decimal places: that is the family percentage. Accumulate the family percentage multiplied by `required_control_count` into a weighted sum, and accumulate `required_control_count` into a weight total. If the weight total is zero, overall coverage is 0.00; otherwise overall coverage is the weighted sum divided by the weight total, rounded half up to two decimal places.

The order of those two roundings is pinned and is not interchangeable: round each family percentage first, then round the weighted mean of the family percentages. Collapsing the calculation into a single ratio of total documented controls to total required controls is a different and incorrect computation — for a baseline requiring 3 controls in family AC with 2 documented and 6 controls in family SC with 1 documented, the pinned order yields 33.34 while the collapsed ratio yields 33.33. The computed coverage read returns `overall_coverage_pct`, the `weight_total` it was divided by, a per-family `family_breakdown`, and the `evaluated_at` instant taken from the logical clock.

### 3.5. Engaging an Assessor: Plan, Cost and Testing Schedule

An **assessment engagement** brings in an accredited third-party assessment organization. The compliance lead creates it with the `offering_id` being assessed, the `assessor_org_name`, the `assessor_user_id` — the opaque operator identifier of the `ThirdPartyAssessor` who will be authorized to act on this engagement — the `contracted_hours` purchased (greater than zero, two decimal places), and the `labor_cost_usd` the assessor charges before program surcharge and hour overage (also greater than zero, two decimal places). The engagement opens in status `DRAFT` with `plan_revision_round` and `findings_reported_count` at 0, `planned_test_start` and `planned_test_end` null, `allocated_hours` at 0 and `unallocated_hours` equal to `contracted_hours`.

Pricing runs at creation and is a three-part rollup. First the program surcharge: the `surcharge_rate` is selected from a tier keyed on `labor_cost_usd` and never on the total — a labor cost below 250000.00 draws a rate of 0.06, a labor cost of at least 250000.00 but below 600000.00 draws 0.045, and a labor cost of 600000.00 or more draws 0.03. `program_surcharge_usd` is `labor_cost_usd` multiplied by `surcharge_rate`, rounded half up to two decimal places, and it is charged on labor alone. Second the hour overage: each impact level comes with an included hour allowance — 400 hours at `LOW`, 900 hours at `MODERATE` and 1600 hours at `HIGH`, read from the offering's `final_impact_level`. Subtract that allowance from `contracted_hours`; if the difference is negative treat it as zero; multiply the result by 120.00 US dollars per hour and round half up to two decimal places to obtain `hour_overage_usd`. Third, `total_cost_usd` is `labor_cost_usd` plus `program_surcharge_usd` plus `hour_overage_usd`, rounded half up to two decimal places. No other engagement participates in the figure.

The assessor then submits the **assessment plan**, supplying `planned_test_start` and `planned_test_end`. Plan submission requires the engagement to be in `DRAFT`, requires the acting `X-User-ID` to equal the engagement's `assessor_user_id` (otherwise `ERR_NOT_RESOURCE_OWNER`), and requires `planned_test_start` to fall strictly before `planned_test_end` (otherwise `ERR_WINDOW_INVALID`). It writes both instants and moves the engagement `DRAFT → PLAN_SUBMITTED`.

Plan approval is where the authorization path first bites. A government reviewer submits a `decision` of `APPROVE` or `REJECT` on a `PLAN_SUBMITTED` engagement. On the `AGENCY_SPONSORED` path the acting party must be an `AgencyAuthorizingOfficial` whose `X-User-ID` equals the offering's `sponsor_agency_id`, and any other agency official is refused with `ERR_SPONSOR_AGENCY_MISMATCH`; on the `PROGRAM_BOARD` path the acting party must be a `ProgramBoardReviewer`, and anyone else is refused with `ERR_WRONG_REVIEW_QUEUE`. An `APPROVE` moves the engagement `PLAN_SUBMITTED → PLAN_APPROVED` and, as a bubble-up, drives the offering `PATH_SELECTED → IN_ASSESSMENT` and increments the offering's `version` by one; the offering must be in `PATH_SELECTED` and the engagement must belong to it. A `REJECT` is the revision loop: the engagement returns `PLAN_SUBMITTED → DRAFT`, `plan_revision_round` increments by one, and both `planned_test_start` and `planned_test_end` are cleared so the assessor must restate the window.

**Test slots** are the testing schedule, and they are drawn against the engagement's hour pool. The assessor schedules a slot by naming the `engagement_id` whose pool funds it, the `family_code` being tested, a `start_at` instant, an `end_at` instant, and the `hours` drawn (greater than zero, two decimal places); the slot's `status` opens at `SCHEDULED`. Slot geometry is half-open — the interval runs from `start_at` inclusive to `end_at` exclusive — and carries no buffer, so a slot beginning at the exact instant a previous slot ends is legal. Two slots of the same engagement conflict when the new slot's start falls strictly before the existing slot's end *and* the existing slot's start falls strictly before the new slot's end, evaluated against the engagement's slots in `SCHEDULED` or `COMPLETED` status; a conflict is refused with `ERR_TEST_SLOT_OVERLAP`. Cancelled slots free their interval and never conflict. A slot whose `start_at` is at or after its `end_at` is refused with `ERR_WINDOW_INVALID`.

The hour ledger is the second gate on a slot. An engagement's `allocated_hours` is the sum of the `hours` of its slots in `SCHEDULED` or `COMPLETED` status, rounded half up to two decimal places, and its `unallocated_hours` is `contracted_hours` less `allocated_hours`, likewise rounded and never negative. Before a slot row is written the requested hours are compared against `unallocated_hours`: hours exceeding the unallocated pool are refused with `ERR_ENGAGEMENT_HOURS_EXHAUSTED`, while hours exactly equal to the pool are accepted and drive `unallocated_hours` to 0.00. The first slot of an engagement also moves it `PLAN_APPROVED → TESTING`; every slot creation increments the engagement's `version` by one. Cancelling a slot moves it `SCHEDULED → CANCELLED`, which is terminal — a slot that is not `SCHEDULED` is refused with `ERR_ALREADY_TERMINAL` — requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, returns the slot's `hours` to `unallocated_hours` while removing them from `allocated_hours`, and increments the engagement's `version` by one. A slot's `status` is one of `SCHEDULED`, `COMPLETED` or `CANCELLED`, and slots are listed per engagement with a `status` filter.

Delivering the **security assessment report** closes out testing. The assessor supplies `findings`, an array of objects each carrying a `control_id`, a `severity` of `HIGH`, `MODERATE` or `LOW`, and a `detected_at` instant; unlike every other array in the system, this one may legally be empty. Report delivery requires the engagement to be in `TESTING`, requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, and requires every element's `detected_at` to be no later than the logical clock — a future detection instant is refused with `ERR_DETECTION_DATE_IN_FUTURE`. On success the engagement moves `TESTING → REPORT_DELIVERED`; one plan-of-action item is opened per findings element with `source` `ASSESSMENT`, its `anchor_at` set to its `detected_at` and its deadline computed as described in §3.6; `findings_reported_count` is set to the number of items created; and every slot of the engagement still in `SCHEDULED` moves `SCHEDULED → COMPLETED`. That last cascade leaves `allocated_hours` unchanged, because completed slots remain inside the allocated total — this is precisely why completion is not a compensation and cancellation is.

`VOIDED` is the engagement's terminal state and is only ever reached as a system consequence of the package review loop running out of rounds, described in §3.7. An engagement in `PLAN_APPROVED`, `TESTING` or `REPORT_DELIVERED` moves to `VOIDED` when the package it backs is rejected after exhausting the revision limit, and in all three cases the void cancels every slot of the engagement still in `SCHEDULED` and returns their hours to `unallocated_hours`.

### 3.6. Findings, Remediation Deadlines, Deviations and Risk

A **plan-of-action item** — a finding — is either opened by the assessment report or filed directly by the compliance lead. A directly filed item names the `offering_id` carrying the finding, the `control_id` the finding was raised against, a `severity` of `HIGH`, `MODERATE` or `LOW`, and a `detected_at` instant that must not be after the logical clock. Its `source` is `ASSESSMENT`, `SCAN` or `SELF_IDENTIFIED` and defaults to `SELF_IDENTIFIED`. Every new item opens with `remediation_status` `OPEN`, `risk_disposition` `NONE`, `closure_reason` null, `granted_extension_days` 0 and `reopen_count` 0.

An item may replace an earlier one. Supplying `supersedes_item_id` names the finding this item replaces; it must belong to the same offering, and a cross-offering pointer is refused with `ERR_SUPERSEDED_ITEM_MISMATCH`, while a pointer at a finding that is already `CLOSED` is refused with `ERR_ALREADY_TERMINAL`. When the pointer is good, the superseded item — whatever its current remediation dimension among `OPEN`, `IN_REMEDIATION` and `AWAITING_VERIFICATION` — is driven to `remediation_status` `CLOSED` with `closure_reason` `SUPERSEDED`, and the authorization's finding counters and residual risk score are recomputed in the same request when the offering is authorized. Findings are listed with filters on `offering_id`, `supersedes_item_id`, `remediation_status`, `risk_disposition`, `severity` and `source`.

**Remediation deadlines** are severity-driven. Base allowances are 30 days for a `HIGH` finding, 90 days for a `MODERATE` finding and 180 days for a `LOW` finding. At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days. Items sourced from an assessment are re-anchored once, at the moment the offering is authorized: for an item whose `source` is `ASSESSMENT`, whose `remediation_status` is not `CLOSED`, and whose `detected_at` falls strictly before the authorization instant, `anchor_at` is moved forward to that authorization instant and `deadline_at` is recomputed from it. Items sourced from a scan or self-identified are never re-anchored. A finding counts as overdue as of a given instant when that instant is at or after `deadline_at` — the boundary instant itself is already overdue, not still on time.

The remediation dimension advances through a single action-bearing operation whose `action` is `START`, `SUBMIT_EVIDENCE`, `VERIFY_CLOSE` or `REOPEN`, and the actions are split between the two operating parties. `START` and `SUBMIT_EVIDENCE` require a `CspComplianceLead` and `VERIFY_CLOSE` and `REOPEN` require a `ThirdPartyAssessor`; the wrong role for the requested action is refused with `ERR_ACTION_ROLE_MISMATCH`. `START` moves `remediation_status` `OPEN → IN_REMEDIATION` and recomputes the authorization's `residual_risk_score` when the offering has an authorization, leaving `risk_disposition` untouched. `SUBMIT_EVIDENCE` moves `IN_REMEDIATION → AWAITING_VERIFICATION` and has no further effect. `VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`. `REOPEN` has two legs and each increments `reopen_count` by one: from `AWAITING_VERIFICATION` it returns the item to `IN_REMEDIATION` with no other effect, and from `CLOSED` — legal only when `closure_reason` is `REMEDIATED` — it returns the item to `IN_REMEDIATION`, clears `closure_reason`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score` so the open/closed partition of §2.11 stays exact.

A **deviation request** is how the provider asks for relief on a finding. Filing one names the `poam_item_id`, a `kind` of `OPERATIONAL_REQUIREMENT`, `FALSE_POSITIVE` or `RISK_ADJUSTMENT`, a non-empty `justification`, and optionally `requested_extension_days`, an integer from 0 through 180 inclusive that defaults to 0 and is only ever honoured for the `OPERATIONAL_REQUIREMENT` kind. Filing requires the finding's `risk_disposition` to be `NONE` and its `remediation_status` not to be `CLOSED` — a closed finding is refused with `ERR_ALREADY_TERMINAL` — and it must be filed against a finding on an offering the acting party is entitled to act on, otherwise `ERR_POAM_OFFERING_MISMATCH`. The request opens in status `SUBMITTED` with `review_queue` null, `routed_by_user_id` and `decided_by_user_id` null, `granted_extension_days` 0, and `submitted_by_user_id` stamped from the filing lead's `X-User-ID`; the finding's `risk_disposition` moves `NONE → DEVIATION_REQUESTED` while its remediation dimension is untouched.

Routing is a board-only act on a `SUBMITTED` request, and the requested `review_queue` — `BOARD` or `AGENCY` — must be legal for the request's `kind`. A `RISK_ADJUSTMENT` may not go to the board queue and an `OPERATIONAL_REQUIREMENT` may not go to the agency queue; the agency queue additionally requires the finding's offering to be on the `AGENCY_SPONSORED` path with a sponsor agency present. Every illegal routing is refused with `ERR_WRONG_REVIEW_QUEUE`. Routing writes `review_queue` and stamps `routed_by_user_id` from the router's `X-User-ID`, moving the request `SUBMITTED → BOARD_REVIEW` or `SUBMITTED → AGENCY_REVIEW`. The fork matters because the two queues carry different approval effects.

Deciding a routed request takes a `decision` of `APPROVE` or `DENY`, writes `decided_by_user_id`, and is terminal — `APPROVED` and `DENIED` both end the request's life. A `BOARD_REVIEW` request may only be decided by a `ProgramBoardReviewer` whose `X-User-ID` differs from `routed_by_user_id`, per §2.8. An `AGENCY_REVIEW` request may only be decided by an `AgencyAuthorizingOfficial` whose `X-User-ID` equals the offering's `sponsor_agency_id`; a foreign agency official is refused with `ERR_POAM_OFFERING_MISMATCH` at tier 33 of §2.7, before the sponsor comparison at tier 34 is ever reached.

The approval effects are branch-specific, and the finding's risk dimension records which branch fired:

- Approving an `OPERATIONAL_REQUIREMENT` request in the board queue sets the request's `granted_extension_days` to the `requested_extension_days` figure, copies that figure onto the finding's own `granted_extension_days`, recomputes the finding's `deadline_at` from its anchor with the extension included, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → EXTENSION_GRANTED`, and recomputes the authorization's `residual_risk_score`.
- Approving a `RISK_ADJUSTMENT` request in the agency queue leaves `granted_extension_days` at 0, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → RISK_ACCEPTED`, and recomputes the authorization's `risk_accepted_findings_count` and `residual_risk_score`, where the accepted finding now contributes at half weight.
- Approving a `FALSE_POSITIVE` request — legal from either queue — leaves `granted_extension_days` at 0, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → FALSE_POSITIVE_ACCEPTED`, and additionally drives the finding's `remediation_status` to `CLOSED` with `closure_reason` `FALSE_POSITIVE`. This is the one place where a risk-dimension decision crosses into the remediation dimension. The authorization's finding counters and `residual_risk_score` are recomputed.
- Denying a request from either queue returns the finding's `risk_disposition` to `NONE`, resets its `granted_extension_days` to 0, recomputes its `deadline_at` without any extension, and recomputes the authorization's `residual_risk_score`.

**Residual risk** is the single number that governs both package submission and continuous monitoring, and it is computed in two variants from the same weighting. Severity weights are 10.0 for `HIGH`, 4.0 for `MODERATE` and 1.0 for `LOW`. Disposition factors are 1.0 for `NONE`, `DEVIATION_REQUESTED` and `EXTENSION_GRANTED`, 0.5 for `RISK_ACCEPTED` and 0.0 for `FALSE_POSITIVE_ACCEPTED`. An overdue finding is multiplied by a further 1.5. The included population is the offering's findings whose `remediation_status` is `OPEN`, `IN_REMEDIATION` or `AWAITING_VERIFICATION`; a `CLOSED` finding never contributes regardless of its `closure_reason`. Walk that population in ascending `created_at` order; for each finding multiply its severity weight by its disposition factor and then by 1.5 if the finding is overdue as of the applicable instant (or by 1.0 if it is not), rounding each finding's contribution half up to two decimal places; sum the contributions; round the sum half up to two decimal places; and take the lesser of that sum and 100.00, which is the ceiling. The floor is 0.00. From the resulting score a `poam_risk_tier` is derived: `NONE` when the score is exactly 0.00, `LOW` when it is greater than 0.00 and less than 10.00, `MODERATE` when it is at least 10.00 and less than 30.00, and `ELEVATED` when it is 30.00 or more.

The two variants differ only in the as-of instant and in which deadline they measure against. The **submission** variant is frozen onto a package at submission time: its as-of instant is the package's `submitted_at`, and the deadline each finding is measured against is its anchor advanced by the severity base allowance *ignoring* `granted_extension_days` — a package snapshot uses assessment-time deadlines and does not benefit from later relief. The **monitoring** variant is the one stored on the authorization as `residual_risk_score`: its as-of instant is the logical clock and the deadline each finding is measured against is its live `deadline_at`, which *includes* `granted_extension_days`, so an approved operational-requirement extension pulls a finding back out of the overdue multiplier. The stored value on the authorization is refreshed only by the mutations named in this section and in §3.7 and §3.8, which means it can lag the live figure once the logical clock advances past a deadline without any write occurring. The risk-summary read exists exactly for that reason: it recomputes the monitoring variant live and returns `residual_risk_score`, the derived `poam_risk_tier`, the lagging `stored_residual_risk_score`, the `open_findings_count`, an `overdue_high_count` of open high-severity findings past their deadline, and the `evaluated_at` instant it used.

### 3.7. Package Submission, Review Rounds and the Authorization Decision

An **authorization package** binds one offering to one assessment engagement for the purpose of a decision. Its creation names the `offering_id`, the `engagement_id` whose report backs it, and the `expected_offering_version` demanded by §2.10. The engagement must belong to the same offering, and a mismatch is refused with `ERR_ENGAGEMENT_OFFERING_MISMATCH`. Revision capacity is capped by construction: an offering may hold at most three package rows in total, so a fourth creation is refused with `ERR_REVISION_LIMIT_EXCEEDED`. On success the package opens in status `DRAFT` with `submission_round` 0, `submitted_at`, `crm_coverage_pct`, `residual_risk_score_at_submission`, `open_findings_at_submission`, `reviewed_by_user_id`, `revision_note` and `letter_reference` all null, and with `authorization_path` copied from the offering — that copy is what later decides who may issue the decision. Creation also increments the offering's `open_package_count` and the offering's `version` by one. Any earlier package of the same offering sitting in `DRAFT` or `REVISION_REQUESTED` is superseded in the same request: it moves to status `SUPERSEDED`, the offering's `open_package_count` decrements by one and its `superseded_package_count` increments by one. Packages are listed with filters on `offering_id`, `engagement_id` and `status`.

Submission is the heaviest gate in the system. It is performed by the offering's owning compliance lead on a package in `DRAFT` or `REVISION_REQUESTED`, and it enforces, in the order given by §2.7: the backing engagement must be in `REPORT_DELIVERED`, else `ERR_ENGAGEMENT_REPORT_NOT_DELIVERED`; customer-responsibility-matrix coverage computed as in §3.4 must be at least 90.00 percent, else `ERR_CRM_COVERAGE_INSUFFICIENT`; the submission-variant residual risk score must be strictly below 50.00, else `ERR_RESIDUAL_RISK_TOO_HIGH`; no finding of the offering may be `HIGH` severity, not `CLOSED`, and already at or past its deadline as of the submission instant, else `ERR_OVERDUE_HIGH_FINDINGS`; and the engagement's `total_cost_usd` must not exceed the offering's `assessment_budget_usd`, else `ERR_ASSESSMENT_BUDGET_EXCEEDED`. A submittable package never carries `submission_round` 3, because a revision request raised at round 3 rejects the package outright rather than returning it for another attempt.

On success the package moves `DRAFT → SUBMITTED` (or `REVISION_REQUESTED → SUBMITTED` on the resubmission leg of the loop, which additionally clears `revision_note`). `submitted_at` is set to the logical clock and `submission_round` increments by one. Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`. The offering moves `IN_ASSESSMENT → PACKAGE_SUBMITTED` and its `version` increments by one; the offering must be in `IN_ASSESSMENT` or already in `PACKAGE_SUBMITTED` for the submission to proceed, which is what permits a resubmission after a revision round.

Program review is a two-step act, and the two steps are deliberately assigned to different people. A `ProgramBoardReviewer` first takes a `SUBMITTED` package into review, moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` from their own `X-User-ID`. From `UNDER_REVIEW` the reviewer may send the package back with a `revision_note`: when `submission_round` is below 3 the package moves `UNDER_REVIEW → REVISION_REQUESTED` and the note is written, which is the cycle back into resubmission. When `submission_round` has reached 3 the same act instead moves the package `UNDER_REVIEW → REJECTED`, still writing `revision_note`, decrements the offering's `open_package_count` by one, and cascades: the backing assessment engagement is driven to `VOIDED`, which in turn cancels every one of that engagement's `SCHEDULED` slots and returns their hours to `unallocated_hours`. The review loop is therefore bounded at three rounds by two independent mechanisms — the three-package ceiling on creation and the round-3 rejection on revision.

The authorization decision closes the package with a `decision` of `AUTHORIZE` or `REJECT` and an optional `risk_acceptance_note` recording the deciding official's acceptance rationale. The package must be `UNDER_REVIEW`. On the `AGENCY_SPONSORED` path the decision belongs to an `AgencyAuthorizingOfficial` whose `X-User-ID` equals the offering's `sponsor_agency_id`, and any other agency official is refused with `ERR_SPONSOR_AGENCY_MISMATCH`. On the `PROGRAM_BOARD` path it belongs to a `ProgramBoardReviewer`, anyone else being refused with `ERR_WRONG_REVIEW_QUEUE`, and that reviewer's `X-User-ID` must differ from the package's `reviewed_by_user_id`, an equal value being refused with `ERR_SEGREGATION_OF_DUTIES`. Both legs decrement the offering's `open_package_count` by one.

A `REJECT` decision moves the package `UNDER_REVIEW → REJECTED`, creates no authorization, and leaves the offering in `PACKAGE_SUBMITTED`. An `AUTHORIZE` decision moves the package `UNDER_REVIEW → AUTHORIZED` and mints its `letter_reference`, formatted as `AUTH-LTR-` followed by the package's `submission_round` and then by the sponsoring agency's `agency_code` on the sponsored path or the literal `BOARD` on the program-board path. It then runs a four-link cascade inside the one request. First, an **authorization** row is created: `offering_id` and `package_id` name their sources, `authorization_path` and `letter_reference` are carried across from the package, `impact_level` freezes the offering's `final_impact_level`, `authorized_at` is set to the logical clock, `expires_at` is set to 1095 days after `authorized_at`, `authorization_status` opens at `AUTHORIZED`, `monitoring_posture` opens at `ACTIVE`, `consecutive_deficient_periods` opens at 0, `reuse_seats_total` opens at 5 with `reuse_seats_granted` 0 and `reuse_seats_available` 5, and `total_findings_count`, `open_findings_count`, `closed_findings_count`, `risk_accepted_findings_count`, `residual_risk_score` and `poam_risk_tier` are computed from the offering's findings as they stand. Second, that row's creation drives the offering `PACKAGE_SUBMITTED → AUTHORIZED` and increments the offering's `version` by one. Third, the first monitoring period is created for the calendar month containing `authorized_at`. Fourth, every `ASSESSMENT`-sourced finding of the offering that is not `CLOSED` and whose `detected_at` precedes `authorized_at` is re-anchored to `authorized_at` and has its `deadline_at` recomputed, as described in §3.6.

Authorizations are read individually with both status dimensions, the stored risk score and the seat ledger exposed, and listed with filters on `offering_id`, `package_id`, `authorization_status` and `monitoring_posture`.

### 3.8. Continuous Monitoring: Monthly Scans and Period Closure

Authorization is not the end of the obligation. Each month of continued operation is represented by a **monitoring period**, identified by its `period_month` in `YYYY-MM` form: four digits, a hyphen, and a month between `01` and `12` inclusive. That value must be unique for the authorization, so a duplicate month is refused with `ERR_DUPLICATE_MONITORING_PERIOD`, and a month string that does not match the form is refused with `ERR_INVALID_REQUEST`. Opening a period may be done by a `CspComplianceLead` or a `ProgramBoardReviewer`, and requires the authorization to be in `authorization_status` `AUTHORIZED` with a `monitoring_posture` other than `ESCALATED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`. The server derives three instants from the month: `window_start` is the first instant of that month inclusive, `window_end` is the first instant of the following month exclusive, and `scan_due_at` is five days after `window_end`. The period opens in status `OPEN` with `accepted_submission_count`, `late_submission_count` and `rejected_submission_count` at 0, `covered_scan_types` an empty array, and `closed_at` null. Its `authorization_id` names the authorization under monitoring.

Inside an open period the compliance lead submits **scan results**. A submission carries `scan_types`, a non-empty duplicate-free array whose members are drawn from `INFRASTRUCTURE`, `WEB_APP`, `DATABASE` and `CONTAINER`. Three of those four are mandatory in every submission: a `scan_types` array that omits `INFRASTRUCTURE`, `WEB_APP` or `DATABASE` is refused with `ERR_INCOMPLETE_SCAN_SET`, while `CONTAINER` is optional. A submission before the period has begun — the logical clock earlier than `window_start` — is refused with `ERR_SCAN_WINDOW_NOT_OPEN`. On acceptance the server records `monitoring_period_id` from the creation path, stamps `submitted_at` from the logical clock and `submitted_by_user_id` from the acting `X-User-ID`, and grades timeliness: if `submitted_at` is at or before the period's `scan_due_at` then `days_late` is 0, otherwise `days_late` is the number of whole 24-hour units that have elapsed since `scan_due_at`, with any partial unit discarded. The submission's `status` follows directly from that figure — `ACCEPTED` when `days_late` is 0, `LATE_ACCEPTED` when `days_late` is 1, 2 or 3, and `REJECTED` when `days_late` is 4 or more. The matching period counter increments by one: `accepted_submission_count` for `ACCEPTED`, `late_submission_count` for `LATE_ACCEPTED`, `rejected_submission_count` for `REJECTED`. The period's `covered_scan_types` is then the sorted union of the `scan_types` of all its submissions whose `status` is `ACCEPTED` or `LATE_ACCEPTED`, so a rejected submission contributes no coverage at all. Each submission increments the period's `version` by one. Submissions are append-only records and, per §2.4, carry only `id` and `created_at`.

Closing a period is a government act performed by a `ProgramBoardReviewer` or an `AgencyAuthorizingOfficial`. The period must still be `OPEN`, else `ERR_ALREADY_TERMINAL`, and the logical clock must be at or after `window_end`, else `ERR_PERIOD_NOT_ENDED`. The verdict is decided by a three-part conjunction: the period's `covered_scan_types` must contain all of `INFRASTRUCTURE`, `WEB_APP` and `DATABASE`; `rejected_submission_count` must be 0; and no finding of the offering may be `HIGH` severity with a `remediation_status` other than `CLOSED` and a `deadline_at` at or before the period's `window_end`. When all three hold the period closes `OPEN → CLOSED_COMPLIANT`; when any one of them fails it closes `OPEN → CLOSED_DEFICIENT`. Either way `closed_at` is stamped from the logical clock and the authorization's `residual_risk_score` is recomputed under the monitoring variant.

A compliant close is restorative. It resets the authorization's `consecutive_deficient_periods` to 0, moves `monitoring_posture` `AT_RISK → ACTIVE` where applicable, and moves `authorization_status` `SUSPENDED → AUTHORIZED` where applicable — with that last move driving the offering `SUSPENDED → AUTHORIZED` and incrementing the offering's `version` by one. Suspension in this system is reversible.

A deficient close increments `consecutive_deficient_periods` by one and then propagates according to the resulting run length. At a run of 1 the `monitoring_posture` moves `ACTIVE → AT_RISK`, and every reuse grant of the authorization in `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `REUSE_ACCEPTED` is moved to `NOTICE_ISSUED`, each such grant incrementing its own `notice_count` by one and the grantee agency's `open_notice_count` by one. At a run of exactly 2 the `authorization_status` moves `AUTHORIZED → SUSPENDED` and the `monitoring_posture` is set to `ESCALATED`, and the offering is driven `AUTHORIZED → SUSPENDED` with its `version` incremented by one; a posture already at `AT_RISK` moving on a run of 2 or more likewise lands at `ESCALATED` and issues notices to the same three access states. At a run of 3 or more the `authorization_status` moves to `REVOKED` from either `AUTHORIZED` or `SUSPENDED`, and every reuse grant of the authorization not already revoked is moved to `REVOKED` with `revoked_reason` `AUTHORIZATION_REVOKED`, each returning its seat to the pool per §2.11.

Two further rules govern what happens after any close. Independently of the compliance verdict, a close performed when the logical clock has reached or passed the authorization's `expires_at` moves `authorization_status` to `EXPIRED` from either `AUTHORIZED` or `SUSPENDED`. And the next month's monitoring period is auto-created by the close whenever the authorization's `authorization_status` after the close is `AUTHORIZED` or `SUSPENDED` — that creation is skipped when a period for that `period_month` already exists for the authorization, and no further period is auto-created once the authorization has reached `REVOKED` or `EXPIRED`.

### 3.9. Significant Changes and Agency Reuse of an Authorization

An authorized offering that wants to change its boundary files a **significant change request** naming the `offering_id`, a `change_kind` of `BOUNDARY_CHANGE`, `NEW_SERVICE` or `TECH_REFRESH`, a non-empty `description`, an implementation window given as `window_start` and `window_end` (both inclusive, with the start strictly before the end), and optionally an `added_service_count` of zero or more services the change brings inside the boundary, defaulting to 0. The server computes `requires_reassessment` as true when the `change_kind` is `BOUNDARY_CHANGE` or when `added_service_count` is 3 or more, and false otherwise. Filing requires the offering to be in status `AUTHORIZED`, moves it `AUTHORIZED → CHANGE_UNDER_REVIEW`, increments its `version` by one, and opens the request in status `SUBMITTED` with `decided_by_user_id` null.

Change windows must be quiet-buffered against each other. For every other change request of the same offering whose `status` is `SUBMITTED` or `APPROVED`, the new window is acceptable only if it is separated from that window by at least seven days on one side or the other: either the new `window_start` is at least seven days after the existing `window_end`, or the existing `window_start` is at least seven days after the new `window_end`. Anything closer is refused with `ERR_CHANGE_WINDOW_BUFFER_VIOLATION`. The comparison is on full instants and the seven-day figure is inclusive, so exactly seven days of separation is accepted while six days, 23 hours, 59 minutes and 59 seconds is not. Windows here are closed intervals with a mandatory buffer, in deliberate contrast to the half-open, buffer-free geometry of test slots in §3.5. A `DENIED` change request never blocks a new window.

Deciding a change request takes a `decision` of `APPROVE` or `DENY` on a `SUBMITTED` request, writes `decided_by_user_id`, and — on the `AGENCY_SPONSORED` path — belongs to the sponsoring agency's official, whose `X-User-ID` must equal the offering's `sponsor_agency_id`, any other agency official being refused with `ERR_SPONSOR_AGENCY_MISMATCH`; on the `PROGRAM_BOARD` path it belongs to a `ProgramBoardReviewer`, anyone else being refused with `ERR_WRONG_REVIEW_QUEUE`. Both outcomes are terminal for the request and both return the offering `CHANGE_UNDER_REVIEW → AUTHORIZED`, incrementing the offering's `version` by one — the offering comes back whether the change was allowed or refused, and the return is only performed once no other change request of that offering remains in `SUBMITTED`. The outcomes differ in what they do to the boundary. An `APPROVE` of a `BOUNDARY_CHANGE` or a `NEW_SERVICE` increments the offering's `boundary_version` by one, and an `APPROVE` of a `NEW_SERVICE` additionally increases the offering's `included_service_count` by the request's `added_service_count`; an `APPROVE` of a `TECH_REFRESH` leaves both untouched. A `DENY` leaves both `boundary_version` and `included_service_count` unchanged. Change requests are listed with filters on `offering_id`, `status` and `change_kind`.

**Agency reuse** is the payoff of the whole programme: a second agency adopts an existing authorization instead of paying for its own. An `AgencyAuthorizingOfficial` requests reuse by naming the `authorization_id` being reused, the `agency_id` doing the reusing — which must be the official's own agency, else `ERR_NOT_RESOURCE_OWNER` — and the `expected_authorization_version` demanded by §2.10. The authorization must be in `authorization_status` `AUTHORIZED` with a `monitoring_posture` other than `ESCALATED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`. The same pair of authorization and agency may not hold two live grants: an existing grant for that pair in any state other than `REVOKED` causes `ERR_DUPLICATE_REUSE_GRANT`. Seats are finite — `reuse_seats_granted` counts the authorization's grants not in `REVOKED` and `reuse_seats_available` is `reuse_seats_total` less that count — and a request arriving when no seat is available is refused with `ERR_REUSE_SEATS_EXHAUSTED`. On success the grant opens with `access_state` `REQUESTED`, `incremental_review_findings_count` 0, `notice_count` 0, `reuse_accepted_at` null and `revoked_reason` null; the granting agency's `reuse_grant_count` increments by one and the authorization's `version` increments by one. Grants are listed with filters on `authorization_id`, `agency_id` and `access_state`.

The reuse conversation then proceeds in three moves. The offering's owning compliance lead grants package access, moving the grant `REQUESTED → PACKAGE_ACCESS_GRANTED`, which is what makes the authorization package readable to the grantee agency under the access rule of §2.1; the acting `X-User-ID` must equal the offering's `owner_user_id`. The grantee agency's official then records an incremental review, supplying a `decision` of `MORE_INFO` or `ACCEPT` together with a `findings_count`, and must be the grant's own agency. A `MORE_INFO` decision writes `incremental_review_findings_count` and moves the grant `PACKAGE_ACCESS_GRANTED → INCREMENTAL_REVIEW`; repeated from `INCREMENTAL_REVIEW` it is a self-loop that overwrites `incremental_review_findings_count` and leaves the state where it is, so the review may iterate as often as the agency needs. An `ACCEPT` decision is legal from `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `NOTICE_ISSUED`, requires the supplied `findings_count` to be no more than 5 — more than that is refused with `ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE` — and requires the authorization to still be in `authorization_status` `AUTHORIZED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`. It writes `incremental_review_findings_count` and `reuse_accepted_at` from the logical clock and moves the grant to `REUSE_ACCEPTED`; when the previous state was `NOTICE_ISSUED`, accepting also decrements the grantee agency's `open_notice_count` by one, which is the loop back out of a monitoring notice into good standing.

A grant may be revoked at any point before it is already revoked, by either the grant's own agency official or a `ProgramBoardReviewer`; a grant already in `REVOKED` is refused with `ERR_ALREADY_TERMINAL`, and an agency official acting on a grant that is not their agency's is refused with `ERR_NOT_RESOURCE_OWNER`. Revocation records a `reason`, stored as `revoked_reason` and drawn from `AGENCY_REQUEST`, `POSTURE_ESCALATION` and `AUTHORIZATION_REVOKED`. It returns the seat — the authorization's `reuse_seats_granted` decreases by one and `reuse_seats_available` increases by one — decrements the agency's `reuse_grant_count` by one, decrements that agency's `open_notice_count` by one when the grant was sitting in `NOTICE_ISSUED`, and increments the authorization's `version` by one. `REVOKED` is terminal for a grant.

## 4. Endpoint Definitions

Operations that bring a new row into existence return `201 Created`. Operations that modify an existing row — including every state transition, every decision and the clock setter — return `200 OK`. Reads return `200 OK`. In the table below, "Any" means all four roles are authorized, subject to the package-read gate described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Register a federal agency that may sponsor offerings and hold reuse grants | ProgramBoardReviewer |
| GET | `/agencies/{id}` | Read one agency including its notice and reuse counters | Any |
| POST | `/control-baselines` | Publish a control baseline for one impact level with its control-family requirements | ProgramBoardReviewer |
| POST | `/offerings` | Create a cloud service offering owned by the acting compliance lead | CspComplianceLead |
| GET | `/offerings/{id}` | Read one offering including computed impact levels and package counters | Any |
| GET | `/offerings` | List offerings with filters and pagination | Any |
| POST | `/offerings/{id}/data-categories` | Declare an information type inside the offering's boundary | CspComplianceLead |
| GET | `/offerings/{id}/data-categories` | List the offering's declared information types | Any |
| POST | `/data-categories/{id}/confirm` | Confirm or withdraw a declared information type | ProgramBoardReviewer, AgencyAuthorizingOfficial |
| POST | `/offerings/{id}/impact-determination` | Determine the final impact level and bind the matching control baseline | ProgramBoardReviewer |
| POST | `/offerings/{id}/path-selection` | Select the authorization path: agency sponsorship or program board | CspComplianceLead |
| GET | `/offerings/{id}/crm-coverage` | Computed read: customer responsibility matrix coverage per family and overall | Any |
| POST | `/control-implementations` | Record a control implementation and its customer responsibility matrix entry | CspComplianceLead |
| PATCH | `/control-implementations/{id}` | Update a control implementation's status or matrix entry | CspComplianceLead |
| GET | `/control-implementations/{id}` | Read one control implementation | Any |
| GET | `/control-implementations` | List control implementations with filters and pagination | Any |
| POST | `/assessment-engagements` | Engage a third-party assessment organization and price the engagement | CspComplianceLead |
| GET | `/assessment-engagements/{id}` | Read one engagement including its hour ledger and cost rollup | Any |
| GET | `/offerings/{id}/assessment-engagements` | List the engagements attached to one offering | Any |
| POST | `/assessment-engagements/{id}/plan` | Submit the assessment plan with its testing window | ThirdPartyAssessor |
| POST | `/assessment-engagements/{id}/plan-approval` | Approve or reject the submitted assessment plan | ProgramBoardReviewer, AgencyAuthorizingOfficial |
| POST | `/test-slots` | Schedule a testing slot and draw its hours from the engagement pool | ThirdPartyAssessor |
| POST | `/test-slots/{id}/cancel` | Cancel a scheduled testing slot and return its hours to the pool | ThirdPartyAssessor |
| GET | `/assessment-engagements/{id}/test-slots` | List the testing schedule of one engagement | Any |
| POST | `/assessment-engagements/{id}/report` | Deliver the assessment report and open one plan-of-action item per finding | ThirdPartyAssessor |
| POST | `/poam-items` | Open a plan-of-action-and-milestones item, optionally superseding an earlier one | CspComplianceLead |
| GET | `/poam-items/{id}` | Read one plan-of-action item including both status dimensions and its deadline | Any |
| GET | `/poam-items` | List plan-of-action items with filters and pagination | Any |
| POST | `/poam-items/{id}/remediation` | Advance the remediation dimension of a plan-of-action item | CspComplianceLead, ThirdPartyAssessor |
| POST | `/deviation-requests` | File a deviation request against an open finding | CspComplianceLead |
| POST | `/deviation-requests/{id}/route` | Route a submitted deviation request to the board or agency queue | ProgramBoardReviewer |
| POST | `/deviation-requests/{id}/decision` | Approve or deny a routed deviation request | ProgramBoardReviewer, AgencyAuthorizingOfficial |
| GET | `/deviation-requests/{id}` | Read one deviation request | Any |
| GET | `/deviation-requests` | List deviation requests with filters and pagination | Any |
| POST | `/authorization-packages` | Create an authorization package, superseding the offering's prior open package | CspComplianceLead |
| POST | `/authorization-packages/{id}/submit` | Submit the package, freezing coverage, risk and finding counts | CspComplianceLead |
| POST | `/authorization-packages/{id}/review` | Take the submitted package into program review | ProgramBoardReviewer |
| POST | `/authorization-packages/{id}/revision-request` | Send the package back for revision, or reject it at the revision limit | ProgramBoardReviewer |
| POST | `/authorization-packages/{id}/decision` | Issue the authorization decision and mint the authorization letter, or reject | ProgramBoardReviewer, AgencyAuthorizingOfficial |
| GET | `/authorization-packages/{id}` | Read one authorization package; agency access is gated per §2.1 | Any |
| GET | `/authorization-packages` | List authorization packages with filters and pagination | Any |
| GET | `/authorizations/{id}` | Read one authorization including both dimensions, risk score and seat ledger | Any |
| GET | `/authorizations` | List authorizations with filters and pagination | Any |
| GET | `/authorizations/{id}/risk-summary` | Computed read: residual risk recomputed live beside the stored value | Any |
| POST | `/authorizations/{id}/monitoring-periods` | Open a monthly continuous-monitoring period | CspComplianceLead, ProgramBoardReviewer |
| GET | `/authorizations/{id}/monitoring-periods` | List the monitoring periods of one authorization | Any |
| GET | `/monitoring-periods/{id}` | Read one monitoring period including counters and covered scan types | Any |
| POST | `/monitoring-periods/{id}/scan-submissions` | Submit the monthly vulnerability scans for a monitoring period | CspComplianceLead |
| GET | `/monitoring-periods/{id}/scan-submissions` | List the scan submissions of one monitoring period | Any |
| POST | `/monitoring-periods/{id}/close` | Close a monitoring period and propagate the posture consequences | ProgramBoardReviewer, AgencyAuthorizingOfficial |
| POST | `/significant-change-requests` | File a significant change request | CspComplianceLead |
| POST | `/significant-change-requests/{id}/decision` | Approve or deny a significant change request and update the boundary | ProgramBoardReviewer, AgencyAuthorizingOfficial |
| GET | `/significant-change-requests/{id}` | Read one significant change request | Any |
| GET | `/significant-change-requests` | List significant change requests with filters and pagination | Any |
| POST | `/reuse-grants` | Request reuse of an existing authorization, consuming one seat | AgencyAuthorizingOfficial |
| POST | `/reuse-grants/{id}/package-access` | Grant the requesting agency read access to the authorization package | CspComplianceLead |
| POST | `/reuse-grants/{id}/incremental-review` | Record the agency's incremental review outcome and accept or iterate | AgencyAuthorizingOfficial |
| POST | `/reuse-grants/{id}/revoke` | Revoke a reuse grant and return its seat to the pool | AgencyAuthorizingOfficial, ProgramBoardReviewer |
| GET | `/reuse-grants/{id}` | Read one reuse grant | Any |
| GET | `/reuse-grants` | List reuse grants with filters and pagination | Any |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramBoardReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_ACTION_ROLE_MISMATCH` | 403 |
| `ERR_WRONG_REVIEW_QUEUE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_OFFERING_NOT_FOUND` | 404 |
| `ERR_DATA_CATEGORY_NOT_FOUND` | 404 |
| `ERR_BASELINE_NOT_FOUND` | 404 |
| `ERR_CONTROL_IMPLEMENTATION_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_TEST_SLOT_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_POAM_ITEM_NOT_FOUND` | 404 |
| `ERR_DEVIATION_NOT_FOUND` | 404 |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_MONITORING_PERIOD_NOT_FOUND` | 404 |
| `ERR_CHANGE_REQUEST_NOT_FOUND` | 404 |
| `ERR_REUSE_GRANT_NOT_FOUND` | 404 |
| `ERR_AGENCY_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_PACKAGE_ACCESS_DENIED` | 403 |
| `ERR_STALE_OFFERING_VERSION` | 412 |
| `ERR_STALE_AUTHORIZATION_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_ENGAGEMENT_REPORT_NOT_DELIVERED` | 409 |
| `ERR_AUTHORIZATION_NOT_ACTIVE` | 409 |
| `ERR_DEVIATION_PENDING_ON_ITEM` | 409 |
| `ERR_INHERITED_OFFERING_NOT_AUTHORIZED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NO_CONFIRMED_DATA_CATEGORY` | 422 |
| `ERR_BASELINE_NOT_AVAILABLE` | 422 |
| `ERR_CRM_TEXT_REQUIRED` | 422 |
| `ERR_INCOMPLETE_SCAN_SET` | 422 |
| `ERR_WINDOW_INVALID` | 422 |
| `ERR_DETECTION_DATE_IN_FUTURE` | 422 |
| `ERR_SCAN_WINDOW_NOT_OPEN` | 422 |
| `ERR_PERIOD_NOT_ENDED` | 409 |
| `ERR_TEST_SLOT_OVERLAP` | 409 |
| `ERR_CHANGE_WINDOW_BUFFER_VIOLATION` | 409 |
| `ERR_DUPLICATE_MONITORING_PERIOD` | 409 |
| `ERR_DUPLICATE_REUSE_GRANT` | 409 |
| `ERR_DUPLICATE_CONTROL_IMPLEMENTATION` | 409 |
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 |
| `ERR_ENGAGEMENT_OFFERING_MISMATCH` | 409 |
| `ERR_POAM_OFFERING_MISMATCH` | 409 |
| `ERR_SPONSOR_AGENCY_MISMATCH` | 403 |
| `ERR_SUPERSEDED_ITEM_MISMATCH` | 409 |
| `ERR_CRM_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_RESIDUAL_RISK_TOO_HIGH` | 422 |
| `ERR_OVERDUE_HIGH_FINDINGS` | 422 |
| `ERR_ENGAGEMENT_HOURS_EXHAUSTED` | 422 |
| `ERR_REUSE_SEATS_EXHAUSTED` | 422 |
| `ERR_SPONSORSHIP_CAPACITY_EXCEEDED` | 422 |
| `ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE` | 422 |
| `ERR_ASSESSMENT_BUDGET_EXCEEDED` | 422 |

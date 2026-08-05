# Physician & Provider Recruitment API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a permanent-placement physician and provider recruitment agency. The platform coordinates the full lifecycle of a healthcare hire: an account team defines client organizations and their fee terms, opens and publishes requisitions by specialty and geography, recruiters source providers and drive them through a screening-to-offer pipeline, client-side contacts review and negotiate, and — once an offer is accepted — the agency shepherds the new hire through licensing and credentialing, relocation reimbursement, onboarding, invoicing, and a post-start guarantee period.

The business is fundamentally a multi-party negotiation orchestrated across several roles that must remain segregated for financial control. Money only becomes real in stages: an *estimated* placement fee is struck when an offer is accepted, and a *final* fee is billed when the signed compensation is known. If a placement falls out inside the guarantee window, the agency must either refund a pro-rated portion of the fee or credit it against a replacement hire, and the client's running net-fee ledger must reflect every one of those movements without drift. Because several people touch the same opening, offer, and placement concurrently, the service applies optimistic concurrency control to the one write that legitimately supersedes prior terms, and it exposes a set of deterministic selectors and calculations so that the same inputs always yield the same assignment and the same cents.

The sections that follow first establish the system-wide contracts — authentication, the response envelope, pagination, identifiers, the logical clock, concurrency, precision, and cascading state — and then narrate the business workflows in the order a real placement travels. Endpoint and error-code summary tables close the document; the behavior behind each row lives in the narrative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming its role. If either header is missing, or `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is checked before authorization.

There are five roles, spelled exactly as follows: `Recruiter`, `AccountManager`, `CredentialingCoordinator`, `ClientContact`, and `PlatformAdmin`.

Four of the five roles are tied to a persisted entity, and their `X-User-ID` is used for ownership checks:

- When `X-User-Role` is `Recruiter`, `X-User-ID` is the `id` of the acting `StaffUser`. Ownership checks compare a resource's owning-recruiter foreign key to `X-User-ID`: a `Recruiter` may act only on `Candidate` records whose `recruiter_id` is theirs and on `Application` records they own.
- When `X-User-Role` is `AccountManager`, `X-User-ID` is the `id` of the acting `StaffUser`. An `AccountManager` conceptually owns the clients they were assigned and the openings, offers, and placements that hang off those clients; in practice this id is consulted only for the four-eyes waiver control described later, and `AccountManager` operations are not otherwise ownership-gated (any `AccountManager` may act on any client, opening, offer, or placement).
- When `X-User-Role` is `CredentialingCoordinator`, `X-User-ID` is the `id` of the acting `StaffUser`. This role manages credentialing files and items and performs placement onboarding.
- When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the `Client` the contact represents; ownership checks on any opening, application, or offer compare that resource's owning `client_id` (directly, or through the application's opening) to `X-User-ID`.

A resource-owning role that acts on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership gating is enforced only on the specific mutating operations narrated in §3 — a `Recruiter` on their own candidates, applications, and the site visits and offers hanging off those applications, and a `ClientContact` on the opening's client for the client-side pipeline-advance and offer-counter actions. Read (GET) endpoints are never ownership-gated: any role authorized for the endpoint may read any resource.

The fifth role is not entity-backed: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server accepts it for provisioning staff users and driving the logical clock but never compares it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 with a minimum of 0. A supplied value outside these bounds is silently clamped into range (a `limit` below 1 becomes 1, above 100 becomes 100, and a negative `offset` becomes 0), and a non-integer or otherwise unparseable `limit`/`offset` falls back to its default. Results are always returned sorted by `created_at` in ascending order, with ties on `created_at` broken by ascending creation order (the order in which the records were inserted). Each list response echoes `limit` and `offset` in `meta` and adds `total_count` (the number of records matching the query before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties, Identifiers, and Timestamps

Every persisted resource carries a server-minted `id` — a UUID with no type prefix, generated by the server and never supplied by the client. Most resources additionally carry three lifecycle fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 on creation and increments by one on every mutation that changes the resource. When a resource is created it is returned with HTTP 201; when it is modified it is returned with HTTP 200.

Timestamps that record real-world moments are set from the **logical clock** (see §2.5), not wall-clock time, so that a resource's `created_at` and any computed date fields are reproducible under test control. Any date or datetime the client supplies (for example an offer's `start_date` or a claim's `fell_out_date`) is stored and echoed in the same ISO 8601 UTC form in which it was received.

### 2.5. The Logical Clock

The service keeps a single logical clock that governs every "current time" decision — offer expiry, onboarding start-date gating, guarantee-window checks, and the stamping of `created_at`/`updated_at`. On server startup the clock reads exactly `2026-05-01T00:00:00Z`; before any clock-setting call it holds this default and never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant. All temporal preconditions in this document ("at or after", "strictly after", "not past") are evaluated against this logical clock.

### 2.6. Optimistic Concurrency Control

One write in the system supersedes prior terms and therefore guards against a stale read using optimistic concurrency control: revising a countered offer. Because a client counter or a previous revise silently advances the offer's `version` between the moment an `AccountManager` reads the offer and the moment they submit new terms, the revise request must carry `expected_offer_version` as a required (non-optional) field holding the `version` the account manager last observed. If `expected_offer_version` does not equal the target offer's current `version`, the revise is rejected with `ERR_STALE_VERSION` (HTTP 412), and no terms change. This is a purely sequential version check: it fires whenever the offer has moved on since the caller's last read, protecting the caller from overwriting terms they never saw. No other endpoint accepts or requires a version field.

### 2.7. Monetary Precision and Rounding

All money is stored and computed in integer cents. Wherever a calculation multiplies by a rate or factor, the product is rounded half up to a whole cent at the point the rule specifies — never truncated, and never left as a fraction. The individual calculations in §3 state exactly where rounding lands relative to flooring, capping, and summing; that ordering is part of the contract, because rounding a sum is not the same as summing rounded lines. Match scores are plain integers in the range 0 to 100 with no rounding.

### 2.8. Cascading State Effects and Parallel Status Axes

Several operations mutate more than one resource. When an operation changes a resource, that resource's `updated_at` is refreshed and its `version` increments; the same is true for every secondary resource the operation touches through a cascade. The specific cascades — an accepted offer creating a placement and a credentialing file and possibly filling and closing out an opening, an approved guarantee claim reopening an opening, a flagged credential item revoking a cleared file — are described where the workflow that triggers them is narrated.

A `Placement` is unusual in carrying **three independent status axes** that evolve separately: `placement_status` (the hire's lifecycle), `fee_status` (the billing state), and `relocation_status` (the relocation-reimbursement state). A transition on one axis never implicitly moves another except where a cascade explicitly says so (for example, approving a guarantee claim moves `placement_status` to `FELL_OUT` and, as a stated side effect, moves `fee_status` to `CREDITED`).

### 2.9. Nested Resource Retrieval and Referential Validation

Some paths address a child through its parent (a credentialing file's items, a placement's relocation expenses). Path identifiers are validated left to right: the parent must exist before the child is looked up, and a missing resource anywhere along the path — or a missing body foreign key — yields `ERR_NOT_FOUND` (HTTP 404). Foreign keys in a request body are validated the same way once the request is found well-formed.

### 2.10. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic:

1. Authentication — headers present and role known, else `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is permitted on this endpoint, else `ERR_UNAUTHORIZED`.
3. Request well-formedness — all required input fields present and correctly typed on mutating endpoints, else `ERR_VALIDATION`.
4. Existence — every path id and body foreign key references an existing resource, validated left to right, else `ERR_NOT_FOUND`.
5. Ownership — an entity-backed role acts only on resources it owns, else `ERR_NOT_RESOURCE_OWNER`.
6. Segregation of duties — the fee-waive four-eyes rule, else `ERR_SEGREGATION_OF_DUTIES`.
7. Optimistic concurrency — `expected_offer_version` matches the current offer `version` on revise, else `ERR_STALE_VERSION`.
8. State legality — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`.
9. Business referential integrity — for example an interviewer being an `ACTIVE` staff user, or the candidate/opening specialty agreement on submit, else `ERR_INTERVIEWER_INVALID` or `ERR_SPECIALTY_MISMATCH` (HTTP 422).
10. Temporal overlap on scheduling — interviewer double-booking or candidate travel conflict, else `ERR_INTERVIEWER_DOUBLE_BOOKED` or `ERR_CANDIDATE_TRAVEL_CONFLICT`.
11. Remaining domain constraints — opening-open-on-submit, comp-in-range, completed-visit-before-offer, credentialing-cleared-before-onboard, guarantee-window, eligible-recruiter-on-publish, and opening-not-already-filled — each with its own error described in §3.
12. Fiscal preconditions — the final compensation being present on invoice, else `ERR_FINAL_COMP_REQUIRED`.

This ordering means, for instance, that a caller lacking permission never learns whether the target resource exists, and a stale-version revise is rejected before its state legality or comp range is examined.

## 3. Business Logic & Workflows

### 3.1. Staff Users and the Client Book

The agency's people are modeled as staff users, each provisioned by a `PlatformAdmin`. A new staff user is created with a `role`, a `full_name`, and an `email`; the `role` is one of `RECRUITER`, `ACCOUNT_MANAGER`, or `CREDENTIALING_COORDINATOR`. A recruiter may additionally be created with `covered_specialties`, a list of specialty values they source for; the field is optional and defaults to an empty list, and it is meaningful only for recruiters — it drives the recruiter selector described in §3.2. Every staff user begins with `status` `ACTIVE`.

A `PlatformAdmin` can later flip a staff user between `ACTIVE` and `INACTIVE`: deactivating drives `ACTIVE → INACTIVE`, and activating drives `INACTIVE → ACTIVE`. Deactivation has two downstream consequences that are enforced elsewhere: an `INACTIVE` recruiter is excluded from the recruiter selector, and an `INACTIVE` staff member cannot serve as a site-visit interviewer (the referential check that guards scheduling rejects them).

Clients are the healthcare organizations the agency recruits for, and each is created by an `AccountManager`. A client carries a `name`, a `region` label, and an `account_manager_id` naming the `ACCOUNT_MANAGER` staff user who owns the relationship — the `account_manager_id` is validated only to reference an existing staff user, its role is not further checked. Three fields fix the commercial terms: `contingency_pct`, the placement-fee rate expressed as a fraction of first-year compensation, which must be greater than 0 and at most 1; `min_fee_cents`, a fee floor in cents that must not be negative; and `guarantee_days`, the length in days of the placement guarantee window, which must be at least 1. A client starts `ACTIVE` with `net_placement_fee_cents` at 0; that running ledger — the sum of recognized placement fees less resolved guarantee credits — is recomputed as fees and credits move, and is surfaced whenever a client is read. Clients may be listed and filtered by `account_manager_id`.

### 3.2. Job Openings and the Recruiter Selector

A requisition is a job opening, created in `DRAFT` by an `AccountManager`. Creation requires the `client_id` of the hiring organization, the `specialty` (one of `FAMILY_MEDICINE`, `CARDIOLOGY`, `PSYCHIATRY`, `ORTHOPEDIC_SURGERY`, or `EMERGENCY_MEDICINE`), a `region` label, and the `region_state` — the two-letter US state code used later for candidate license-state matching. The compensation band is given by `comp_min_cents` and `comp_max_cents`, both non-negative, with `comp_max_cents` at least equal to `comp_min_cents`. Two optional inputs shape fees and headcount: `is_hard_to_fill`, a scarcity flag defaulting to false that later applies a hard-to-fill multiplier to the placement fee, and `positions_total`, the headcount to fill, defaulting to 1 and never below 1. A freshly created opening has `positions_filled` at 0, a null `recruiter_id`, and `status` `DRAFT`.

Publishing an opening advances it `DRAFT → OPEN` and is where a recruiter is assigned. Before the transition succeeds, the **recruiter selector** runs: the eligible pool is every staff user whose `role` is `RECRUITER`, whose `status` is `ACTIVE`, and whose `covered_specialties` includes this opening's `specialty`. If that pool is empty, publishing is rejected with `ERR_NO_ELIGIBLE_RECRUITER` and no assignment is made. Otherwise each eligible recruiter is ranked by their **open pipeline load** — the number of applications assigned to that recruiter whose `stage` is any of `SOURCED`, `SCREENED`, `SUBMITTED`, `INTERVIEWING`, or `OFFER_STAGE` — in ascending order, so the least-loaded recruiter wins. Ties are broken by earliest `created_at`, ascending, and — when `created_at` is also identical — by earliest creation order (insertion sequence), never by `id`. The winner's staff id is written to the opening's `recruiter_id`.

Once open, an opening can be put on hold (`OPEN → ON_HOLD`) and resumed (`ON_HOLD → OPEN`) by an `AccountManager`, and it can be closed from `OPEN`, `ON_HOLD`, or `FILLED` to the terminal `CLOSED`. Two further transitions are driven by the system rather than by a user. When a placement is created and the opening's `positions_filled` reaches `positions_total`, the opening moves `OPEN → FILLED`. When a live placement on a filled opening later falls out and `positions_filled` drops below `positions_total`, the opening moves `FILLED → OPEN` again. `positions_filled` is always the count of that opening's placements whose `placement_status` is `PRE_START`, `ACTIVE`, or `GUARANTEE_MET` — placements that are `FELL_OUT` or `CANCELLED` do not count.

The fill transition carries a cascade. When an opening reaches `FILLED`, every application on that opening whose `stage` is `SOURCED`, `SCREENED`, `SUBMITTED`, `INTERVIEWING`, or `OFFER_STAGE` is moved to `REJECTED` with `reject_reason` `OPENING_FILLED`; and for every such application that had an offer in `EXTENDED` or `COUNTERED`, that offer is moved to `RESCINDED`. Openings may be listed and filtered by `client_id`, `recruiter_id`, and `specialty`.

### 3.3. Candidates and the Application Pipeline

A `Recruiter` registers providers as candidates. A candidate is created with a `recruiter_id` that must equal the acting recruiter's own id, a `full_name`, a `specialty` drawn from the same five-value set as openings, a `home_region` label, an optional `license_states` list of two-letter US state codes (defaulting to empty), and a `desired_comp_cents` first-year target that must not be negative. A new candidate is `ACTIVE`; over its life a candidate may also become `PLACED` or `DO_NOT_CONTACT`. Candidates may be listed and filtered by `recruiter_id` and `specialty`.

An application ties a candidate to an opening. A `Recruiter` sources a candidate onto an opening by supplying `candidate_id` and `opening_id`; the application's `recruiter_id` is copied from the candidate's owning recruiter at creation, its `stage` starts at `SOURCED`, and its `match_score` starts at 0. Applications may be listed and filtered by `opening_id`, `candidate_id`, `recruiter_id`, and `stage`. Sourcing a candidate onto an opening that has already reached `FILLED` is rejected with `ERR_OPENING_FILLED`, since a filled opening has no remaining headcount to pursue.

The pipeline advances through a sequence of stage transitions. A recruiter screens an application (`SOURCED → SCREENED`), and screening recomputes the `match_score`. The match score is a 0-to-100 figure and is purely informational — it is never used as a business selector. It is computed by starting at zero and adding a fixed weight for each attribute that agrees between the candidate and the opening: 50 points when the candidate's `specialty` equals the opening's `specialty`, 30 points when the candidate's `home_region` equals the opening's `region`, and 20 points when the opening's `region_state` appears in the candidate's `license_states`. A perfectly aligned candidate therefore scores 100.

A recruiter then submits a screened application to the client (`SCREENED → SUBMITTED`). Submission has two preconditions: the referenced opening's `status` must be `OPEN`, otherwise the request is rejected with `ERR_OPENING_NOT_OPEN`; and the candidate's `specialty` must equal the opening's `specialty`, otherwise it is rejected with `ERR_SPECIALTY_MISMATCH`. From here the acting party shifts to the client side. A `ClientContact` who owns the opening's client advances a submitted application to interview (`SUBMITTED → INTERVIEWING`) or passes on it (`SUBMITTED → REJECTED`, setting `reject_reason` to `CLIENT_PASS`); a client contact acting on an application whose opening belongs to a different client is rejected for lack of ownership. A recruiter may withdraw a candidate from any of `SOURCED`, `SCREENED`, `SUBMITTED`, or `INTERVIEWING`, moving the application to the terminal `WITHDRAWN` and setting `reject_reason` to `WITHDRAWN_BY_CANDIDATE`.

Two stage changes happen only as system consequences of events narrated elsewhere. When an offer is created for an application, the application moves `INTERVIEWING → OFFER_STAGE`; this requires at least one site visit on the application in `COMPLETED` status, otherwise offer creation is rejected with `ERR_NO_COMPLETED_SITE_VISIT`. When that offer is accepted, the application moves `OFFER_STAGE → PLACED`. Finally, when an opening reaches `FILLED` through a sibling placement, any still-live application on it — one in `SUBMITTED`, `INTERVIEWING`, or `OFFER_STAGE` — is moved to `REJECTED` with `reject_reason` `OPENING_FILLED`; for an application caught at `OFFER_STAGE`, its `EXTENDED` or `COUNTERED` offer is `RESCINDED` at the same time. The `reject_reason` is always one of `CLIENT_PASS`, `OPENING_FILLED`, or `WITHDRAWN_BY_CANDIDATE`.

### 3.4. Site Visits and Scheduling Conflicts

Interviews and on-site visits are scheduled by a `Recruiter` against an application. A site visit is created with an `application_id`, an `interviewer_user_id` naming the interviewing staff member, a `scheduled_start` and a `scheduled_end` (both ISO 8601 UTC, with the end strictly after the start), and a `location` label. It begins in `SCHEDULED` and can later move to `COMPLETED`, `CANCELLED`, or `NO_SHOW`. Site visits may be listed and filtered by `application_id` and `interviewer_user_id`.

Before a scheduled visit is persisted, three guards run. The interviewer named by `interviewer_user_id` must be an `ACTIVE` staff user; otherwise the request is rejected with `ERR_INTERVIEWER_INVALID`. Then two temporal overlap checks apply, and they use different geometries.

The **interviewer** check treats each visit as a half-open interval, so that back-to-back bookings that merely touch at an endpoint are allowed. Writing the new visit's window as beginning at its `scheduled_start` and ending at its `scheduled_end`, the request is rejected with `ERR_INTERVIEWER_DOUBLE_BOOKED` if there exists any other `SCHEDULED` visit on the same `interviewer_user_id` whose window overlaps it — that is, the new start falls before the existing end and the existing start falls before the new end. When the new visit begins exactly when another ends, or ends exactly when another begins, there is no conflict.

The **candidate** check is buffered and closed. The relevant candidate is the one on the visit's application, and the check considers every `SCHEDULED` visit on any application belonging to that same candidate. Each such existing visit's window is expanded by a candidate travel buffer of 120 minutes on both sides; if that expanded window intersects the new visit's window, the request is rejected with `ERR_CANDIDATE_TRAVEL_CONFLICT`. Equivalently, a gap of less than 120 minutes between the two visits is rejected, while a gap of exactly 120 minutes is allowed. In both overlap checks, only `SCHEDULED` visits are considered; visits in `CANCELLED`, `COMPLETED`, or `NO_SHOW` are ignored.

A recruiter completes a visit (`SCHEDULED → COMPLETED`), which is what makes the application eligible for offer creation, or records it as `SCHEDULED → CANCELLED` or `SCHEDULED → NO_SHOW`.

### 3.5. Offers and the Negotiation Loop

An `AccountManager` extends an offer against an application. Creating an offer requires the `application_id`, a `base_salary_cents` (non-negative first-year base), a `start_date`, and an `expires_at` instant; it also accepts an optional `sign_on_bonus_cents` (defaulting to 0) and an optional `relocation_cap_cents` reimbursement ceiling (defaulting to 0). A new offer is `EXTENDED` with `round_number` 1; its `extended_by_user_id` records the acting account manager, and its `offered_first_year_comp_cents` is set to the sum of `base_salary_cents` and `sign_on_bonus_cents`. Creating the offer is also what advances the application `INTERVIEWING → OFFER_STAGE`, which — as noted above — requires a `COMPLETED` site visit on that application, failing with `ERR_NO_COMPLETED_SITE_VISIT` otherwise. The offered `base_salary_cents` must fall within the opening's band, at least `comp_min_cents` and at most `comp_max_cents`; a value outside that band is rejected with `ERR_COMP_OUT_OF_RANGE`. Offers may be listed and filtered by `application_id`.

Negotiation is a cyclic loop between the client and the account team. A `ClientContact` who owns the opening's client may counter an extended offer, moving it `EXTENDED → COUNTERED`. The account manager answers a counter by revising it back `COUNTERED → EXTENDED` with fresh terms. A revise is the one write in the system guarded by optimistic concurrency: it must carry `expected_offer_version` holding the `version` the account manager last read, and if that does not match the offer's current `version` the revise is rejected with `ERR_STALE_VERSION` (HTTP 412) — this happens whenever a client counter or an earlier revise advanced the offer's version between the account manager's read and this call. A revise may update any of `base_salary_cents`, `sign_on_bonus_cents`, `start_date`, and `expires_at`; if a new `base_salary_cents` is supplied it, too, must lie within the opening's `comp_min_cents`-to-`comp_max_cents` band, failing with `ERR_COMP_OUT_OF_RANGE`. A successful revise increments `round_number` by one, recomputes `offered_first_year_comp_cents` from the current base and sign-on figures, sets `extended_by_user_id` to the acting account manager, and increments the offer's `version` by one.

An offer terminates in one of four ways. A `Recruiter`, acting for the candidate, accepts an extended offer (`EXTENDED → ACCEPTED`) provided the offer is not past its `expires_at`, or declines it (`EXTENDED → DECLINED`, and a countered offer may likewise be `COUNTERED → DECLINED`). An `AccountManager` may rescind an offer from either `EXTENDED` or `COUNTERED` (to `RESCINDED`), or expire an extended offer (`EXTENDED → EXPIRED`) — but expiry is legal only once the logical clock has reached or passed `expires_at`, and an attempt before that instant is rejected with `ERR_INVALID_STATE`. Acceptance triggers the placement cascade described next.

### 3.6. Acceptance, Placement Creation, and the Fill Cascade

Accepting an offer is the root of a multi-resource cascade. The application moves `OFFER_STAGE → PLACED` and the candidate's `status` becomes `PLACED`. A new placement is created, carrying system-copied links to its `offer_id`, `application_id`, `client_id`, `candidate_id`, and `opening_id`, with its `start_date` copied from the accepted offer and its `relocation_cap_cents` copied from the offer's relocation cap. The placement begins with `placement_status` `PRE_START`, `fee_status` `PENDING`, and `relocation_status` `NONE`.

At acceptance the **estimate variant** of the placement fee is computed and stored in `fee_estimate_cents`. The fee starts from the first-year compensation figure — for the estimate this is the offer's `offered_first_year_comp_cents`. That figure is multiplied by the client's `contingency_pct`, and then by a hard-to-fill multiplier of 1.20 when the opening's `is_hard_to_fill` flag is set, or by 1.0 otherwise. The product of compensation, contingency rate, and multiplier is rounded half up to whole cents to give a raw fee, and the stored fee is the greater of that raw fee and the client's `min_fee_cents` floor. The half-up rounding is applied to the percentage product before the floor is applied.

Acceptance also creates a `CredentialingFile` for the placement in `NOT_STARTED`, linking the new file's `placement_id` and `candidate_id`. Finally, the opening's `positions_filled` is increased by one; if that increase makes `positions_filled` equal `positions_total`, the opening moves `OPEN → FILLED`, which in turn fires the sibling cascade from §3.2 — all still-live applications on the opening are rejected with `reject_reason` `OPENING_FILLED`, and their `EXTENDED` or `COUNTERED` offers are rescinded. Placements may be read individually and listed, filtered by `opening_id`, `client_id`, `candidate_id`, `application_id`, and `offer_id`.

### 3.7. Credentialing

Each placement's credentialing is tracked by the `CredentialingFile` created at acceptance, whose `overall_status` is not set directly but derived from its child credential items; the file may be listed and filtered by `placement_id` and `candidate_id`. A `CredentialingCoordinator` adds credential items to a file identified by its `credentialing_file_id`, each with an `item_type` — one of `STATE_LICENSE`, `DEA_REGISTRATION`, `BOARD_CERTIFICATION`, `MALPRACTICE_HISTORY`, or `REFERENCE` — and an `is_required` flag defaulting to true that marks whether the item must be verified for the file to clear. A new item begins `PENDING`. Items on a file may be listed via the file.

A credentialing coordinator drives each item through its own machine: submit (`PENDING → SUBMITTED`), verify (`SUBMITTED → VERIFIED`), flag (from either `SUBMITTED` or `VERIFIED` to `FLAGGED`), and resubmit (`FLAGGED → SUBMITTED`). Every one of these transitions bubbles up to recompute the parent file's `overall_status`, which follows these rules: the file leaves `NOT_STARTED` for `IN_PROGRESS` as soon as any child item becomes `SUBMITTED` or `VERIFIED`; it becomes `CLEARED` from `IN_PROGRESS` exactly when every item with `is_required` true is `VERIFIED` and no item is `FLAGGED`; it becomes `FLAGGED` whenever any child item is flagged (including a `VERIFIED` item being flagged, which revokes a previously `CLEARED` file, driving `CLEARED → FLAGGED`); and a `FLAGGED` file returns to `IN_PROGRESS` once the flagged item is resubmitted and no item remains flagged. A cleared credentialing file is the precondition for onboarding.

### 3.8. Onboarding, Billing, Relocation, and the Client Ledger

A placement carries three independent status axes, and this subsection covers all three. On the **lifecycle axis**, a `CredentialingCoordinator` onboards a placement (`PRE_START → ACTIVE`) once two conditions hold: the placement's credentialing file `overall_status` is `CLEARED`, otherwise the request is rejected with `ERR_CREDENTIALING_NOT_CLEARED`; and the logical clock has reached or passed the placement's `start_date`, otherwise it is rejected with `ERR_INVALID_STATE`. Onboarding computes the `guarantee_end_date` as the placement's `start_date` plus the client's `guarantee_days`, counted in whole days. Later, an `AccountManager` may mark the guarantee met (`ACTIVE → GUARANTEE_MET`), which is legal only once the logical clock is strictly past `guarantee_end_date`, failing with `ERR_INVALID_STATE` otherwise. An `AccountManager` may also cancel a placement that has not yet started (`PRE_START → CANCELLED`), permitted only while `placement_status` is `PRE_START`; cancellation decrements the opening's `positions_filled` by one — reopening a `FILLED` opening to `OPEN` if that drop applies — and returns the candidate's `status` to `ACTIVE`.

On the **billing axis**, which evolves independently of the lifecycle axis, an `AccountManager` invoices a placement (`fee_status` `PENDING → INVOICED`). Invoicing is permitted only when `placement_status` is `ACTIVE`, otherwise `ERR_INVALID_STATE`, and it requires `final_first_year_comp_cents` in the request; if that final compensation is absent the request is rejected with `ERR_FINAL_COMP_REQUIRED`. Invoicing computes the **final variant** of the placement fee and stores it in `placement_fee_cents`. The final fee uses the identical arithmetic as the estimate — first-year compensation times `contingency_pct` times the hard-to-fill multiplier (1.20 when `is_hard_to_fill`, else 1.0), rounded half up before taking the maximum with `min_fee_cents` — but the first-year compensation input is the signed `final_first_year_comp_cents` rather than the offered snapshot, so the two figures may differ. The account manager later marks an invoiced placement paid (`INVOICED → PAID`). Alternatively, a fee may be waived (`fee_status` `PENDING → WAIVED`); waiving is subject to a four-eyes control — the acting account manager's id must differ from the `extended_by_user_id` recorded on the placement's originating offer, and if the same person who extended that offer attempts the waiver it is rejected with `ERR_SEGREGATION_OF_DUTIES`.

The client's `net_placement_fee_cents` ledger is recomputed whenever a fee is invoiced or marked paid and whenever a guarantee claim is resolved. Its value is the recognized fees minus the resolved credits: the recognized total sums `placement_fee_cents` across the client's placements whose `fee_status` is `INVOICED`, `PAID`, or `CREDITED` (placements that are `WAIVED` or still `PENDING` are excluded), and the credited total sums the `credit_cents` of the client's guarantee claims in `RESOLVED_REFUND` or `RESOLVED_REPLACEMENT`. A credited placement deliberately stays inside the recognized total so that an invoice-then-credit pair nets to billed-minus-credit with no drift; the ledger invariant is that net always equals recognized minus credited.

On the **relocation axis**, a `Recruiter` or an `AccountManager` adds relocation expense lines to a placement. Each line has a `category` — one of `MOVERS`, `TEMP_HOUSING`, `FLIGHTS`, `LICENSING_FEES`, or `OTHER` — a non-negative `amount_cents`, and an optional `is_taxable` flag defaulting to false. A line begins `SUBMITTED`. An `AccountManager` approves a line by supplying its `expense_id` (moving that line `SUBMITTED → APPROVED`), which sets the placement's `relocation_status` to `APPROVED` unless it has already reached `REIMBURSED`, or rejects a line by `expense_id` (`SUBMITTED → REJECTED`). Once the placement's `relocation_status` is `APPROVED`, an `AccountManager` reimburses (`APPROVED → REIMBURSED`); attempting reimbursement when `relocation_status` is not `APPROVED` is rejected with `ERR_INVALID_STATE`. Reimbursement computes `relocation_reimbursed_cents` over only the placement's `APPROVED` lines (`SUBMITTED` and `REJECTED` lines are excluded): each taxable line's `amount_cents` is grossed up by a tax factor of 1.25 and rounded half up to whole cents, while a non-taxable line contributes its raw `amount_cents`; these per-line amounts are summed after their individual rounding, and the reimbursed total is capped at the placement's `relocation_cap_cents`. The per-line rounding happens before summing — the total is not rounded after the fact.

### 3.9. Guarantee Claims and Fallout

If a placed provider leaves, a `Recruiter` or an `AccountManager` files a guarantee claim against the placement. A claim is filed with the `placement_id`, a `fell_out_date` (the date the provider left), and a free-text `reason`; on filing it begins in `FILED`, its `client_id` is copied from the placement, and its `days_worked` is computed as the whole-day count from the placement's `start_date` to the `fell_out_date`, floored to a whole number of days. A claim also carries a `replacement_placement_id`, which is null for a refund resolution and set for a replacement resolution, and a `credit_cents` figure computed at resolution. Claims may be listed and filtered by `placement_id` and `client_id`.

An `AccountManager` approves a filed claim (`FILED → APPROVED`) subject to two preconditions: the placement's `placement_status` must be `ACTIVE`, otherwise `ERR_INVALID_STATE`; and the `fell_out_date` must be on or before the placement's `guarantee_end_date` — the boundary is inclusive — otherwise the claim is rejected with `ERR_GUARANTEE_WINDOW_EXPIRED`. Approval is itself a cascade root: the placement moves `ACTIVE → FELL_OUT`, its `fee_status` becomes `CREDITED`, and the opening's `positions_filled` is decremented by one, reopening a `FILLED` opening to `OPEN` if the count now falls below `positions_total`. An account manager may instead deny a filed claim (`FILED → DENIED`).

An approved claim is resolved one of two ways, and the resolution is what computes `credit_cents` and moves the client ledger. A **refund** resolution (`APPROVED → RESOLVED_REFUND`) returns cash pro-rata to the unworked portion of the guarantee. Compute the unworked fraction as the client's `guarantee_days` minus the claim's `days_worked`, divided by `guarantee_days`, floored at zero so it is never negative; the `credit_cents` is the placement's `placement_fee_cents` multiplied by that unworked fraction, rounded half up to whole cents. A **replacement** resolution (`APPROVED → RESOLVED_REPLACEMENT`) supplies a `replacement_placement_id` that must reference a placement on the same opening currently in `PRE_START` or `ACTIVE`, otherwise the request is rejected with `ERR_INVALID_STATE`; here `credit_cents` is not time-prorated but is the full original `placement_fee_cents`, capped at the replacement placement's `fee_estimate_cents` (that is, the smaller of the two). Either resolution recomputes the client's `net_placement_fee_cents`, subtracting the newly computed credit.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. Every transition endpoint (those whose path ends in `transition` or `advance`) selects the specific transition through an `action` field in its request body, together with any parameters that transition requires; the offer-revise endpoint is the exception, taking its new terms directly rather than an `action`. Every mutating action's request body, side effects, and preconditions are described in the §3 narratives — the table below lists only the transport contract.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/staff-users` | Create a staff user | PlatformAdmin |
| GET | `/staff-users/{staffUserId}` | Get a staff user | PlatformAdmin, Recruiter, AccountManager, CredentialingCoordinator |
| POST | `/staff-users/{staffUserId}/transition` | Activate/deactivate a staff user | PlatformAdmin |
| POST | `/clients` | Create a client with fee terms | AccountManager |
| GET | `/clients/{clientId}` | Get a client including net placement fee | PlatformAdmin, AccountManager, ClientContact |
| GET | `/clients` | List clients | PlatformAdmin, AccountManager |
| POST | `/job-openings` | Create a job opening (DRAFT) | AccountManager |
| GET | `/job-openings/{openingId}` | Get a job opening | PlatformAdmin, AccountManager, Recruiter, ClientContact |
| GET | `/job-openings` | List job openings | PlatformAdmin, AccountManager, Recruiter |
| POST | `/job-openings/{openingId}/transition` | Publish/hold/resume/close an opening | AccountManager |
| POST | `/candidates` | Create a candidate | Recruiter |
| GET | `/candidates/{candidateId}` | Get a candidate | PlatformAdmin, Recruiter, AccountManager |
| GET | `/candidates` | List candidates | PlatformAdmin, Recruiter, AccountManager |
| POST | `/applications` | Source a candidate onto an opening | Recruiter |
| GET | `/applications/{applicationId}` | Get an application | PlatformAdmin, Recruiter, AccountManager, ClientContact |
| GET | `/applications` | List applications | PlatformAdmin, Recruiter, AccountManager, ClientContact |
| POST | `/applications/{applicationId}/advance` | Advance the pipeline | Recruiter, ClientContact |
| POST | `/site-visits` | Schedule a site visit | Recruiter |
| GET | `/site-visits/{siteVisitId}` | Get a site visit | PlatformAdmin, Recruiter, AccountManager |
| GET | `/site-visits` | List site visits | PlatformAdmin, Recruiter, AccountManager |
| POST | `/site-visits/{siteVisitId}/transition` | Complete/cancel/no-show a visit | Recruiter |
| POST | `/offers` | Extend an offer | AccountManager |
| GET | `/offers/{offerId}` | Get an offer | PlatformAdmin, AccountManager, Recruiter, ClientContact |
| GET | `/offers` | List offers | PlatformAdmin, AccountManager, Recruiter, ClientContact |
| POST | `/offers/{offerId}/transition` | Counter/accept/decline/rescind/expire an offer | AccountManager, Recruiter, ClientContact |
| POST | `/offers/{offerId}/revise` | Revise a countered offer (OCC) | AccountManager |
| GET | `/placements/{placementId}` | Get a placement | PlatformAdmin, AccountManager, Recruiter, CredentialingCoordinator |
| GET | `/placements` | List placements | PlatformAdmin, AccountManager, Recruiter, CredentialingCoordinator |
| POST | `/placements/{placementId}/transition` | Placement lifecycle, fee, and relocation actions | AccountManager, CredentialingCoordinator |
| POST | `/placements/{id}/relocation-expenses` | Add a relocation expense line | Recruiter, AccountManager |
| GET | `/placements/{id}/relocation-expenses` | List a placement's relocation expenses | PlatformAdmin, AccountManager, Recruiter |
| GET | `/credentialing-files/{credentialingFileId}` | Get a credentialing file | PlatformAdmin, CredentialingCoordinator, AccountManager |
| GET | `/credentialing-files` | List credentialing files | PlatformAdmin, CredentialingCoordinator, AccountManager |
| POST | `/credentialing-files/{id}/items` | Add a credential item | CredentialingCoordinator |
| GET | `/credentialing-files/{id}/items` | List a file's credential items | PlatformAdmin, CredentialingCoordinator, AccountManager |
| POST | `/credential-items/{credentialItemId}/transition` | Submit/verify/flag/resubmit an item | CredentialingCoordinator |
| POST | `/guarantee-claims` | File a guarantee claim | Recruiter, AccountManager |
| GET | `/guarantee-claims/{guaranteeClaimId}` | Get a guarantee claim | PlatformAdmin, AccountManager, Recruiter |
| GET | `/guarantee-claims` | List guarantee claims | PlatformAdmin, AccountManager, Recruiter |
| POST | `/guarantee-claims/{guaranteeClaimId}/transition` | Approve/deny/resolve a claim | AccountManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INTERVIEWER_INVALID` | 422 |
| `ERR_SPECIALTY_MISMATCH` | 422 |
| `ERR_INTERVIEWER_DOUBLE_BOOKED` | 409 |
| `ERR_CANDIDATE_TRAVEL_CONFLICT` | 409 |
| `ERR_OPENING_NOT_OPEN` | 409 |
| `ERR_COMP_OUT_OF_RANGE` | 422 |
| `ERR_NO_COMPLETED_SITE_VISIT` | 409 |
| `ERR_CREDENTIALING_NOT_CLEARED` | 409 |
| `ERR_GUARANTEE_WINDOW_EXPIRED` | 422 |
| `ERR_NO_ELIGIBLE_RECRUITER` | 409 |
| `ERR_OPENING_FILLED` | 409 |
| `ERR_FINAL_COMP_REQUIRED` | 422 |

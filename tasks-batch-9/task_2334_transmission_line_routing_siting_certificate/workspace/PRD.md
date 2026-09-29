# Transmission Siting API — Product Requirements Document

## 1. Introduction

Getting a high-voltage transmission line built is less an engineering problem than a documentary one. Before a single structure is set, an electric transmission developer must prove that the line is needed at all — and that no combination of storage, demand response or generation could relieve the same deficiency more cheaply. It must then draw candidate corridors across land that other people own, farm, worship on and regulate; publish those corridors; absorb what the affected public says about them; and refine them in response. Only then does a filing go to the state siting commission, where landowners and interest groups can intervene, an examiner takes evidence, and the commission either issues a certificate laden with mitigation conditions or refuses one. After the order comes the hard part: buying rights of way parcel by parcel, obtaining federal permits wherever the line crosses public land or navigable water, and then building under continuous compliance monitoring against every condition the order imposed.

This service is the system of record for that entire arc, mounted under the `/siting` prefix. It is deliberately unforgiving about sequence. A route cannot be nominated until it has survived a comment-and-refinement cycle and its constraint density has fallen inside the acceptable band. An application cannot be filed unless a second developer — not the author — has certified the need case. Construction cannot start on a segment until certificate posture, seasonal restrictions, federal crossing permits, easement acquisition and project escrow all line up simultaneously. Every one of those couplings exists in the real regulatory world, and the API refuses to let a client shortcut any of them.

Two design commitments run through everything below. First, **the record is append-forward**: findings, offers, comments and rulings accumulate, and derived figures such as compliance indices and escrow requirements are recomputed from that history rather than patched in place. Second, **the same underlying fact is often measured twice** — a desk-study constraint score alongside a filing-grade one, a negotiated offer alongside a condemnation award, a recoverable rolling compliance index alongside a permanent cumulative one. Implementers should expect divergent variants of the same calculation to coexist by design, and should never collapse one into the other.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Headers and Role-Based Access Control

Every request to the API — reads included — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If `X-User-Role` is not one of the seven role names below, or is a valid role that the endpoint does not authorize, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Seven roles participate:

- **`Developer`** — electric transmission developer staff. Builds the need case, publishes and nominates routes, files and amends the application, funds escrow, acquires easements and runs construction.
- **`RouteAnalyst`** — routing and environmental analyst. Adds segments, runs constraint mapping, screens alternatives, dispositions public comments and drives route refinements.
- **`CommissionStaff`** — state siting commission staff. Reviews filings, rules on intervention petitions, records the order, waives conditions, records condemnation awards, rescinds payments and closes out certificates.
- **`HearingExaminer`** — administrative hearing examiner. Schedules and holds sessions and closes the evidentiary record.
- **`Landowner`** — affected landowner of record. Comments, petitions to intervene and responds to easement offers.
- **`FederalPermitOfficer`** — federal land or waterway agency officer acting on crossing permits.
- **`ComplianceMonitor`** — independent construction compliance monitor who files findings against certificate conditions.

Six of the seven roles are **opaque identities**. When `X-User-Role` is `Developer`, `RouteAnalyst`, `CommissionStaff`, `HearingExaminer`, `FederalPermitOfficer` or `ComplianceMonitor`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server records it where a workflow calls for attribution — as `authored_by_user_id` and `certified_by_user_id` on a planning study, `filed_by_user_id` on an application, `presiding_user_id` on a hearing session, `ruled_by_user_id` on an intervention, and `issued_by_user_id` on a certificate — and compares recorded values against one another for the segregation-of-duties rules in §2.10, but it never compares them to any row's `id`.

`Landowner` is the one **entity-backed identity**. When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the acting `Landowner` row; ownership checks on any resource that references a landowner compare that resource's landowner reference to `X-User-ID`. Concretely, a landowner responding to an easement offer must be the tract's `landowner_id`, and a landowner filing a public comment must supply their own identifier as `commenter_landowner_id`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); that ownership rule guards exactly two write operations — the easement offer response and public comment intake.

All read endpoints are open to all seven roles. Write authority is listed per endpoint in §4.

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

### 2.3. Pagination, Ordering and Collection Filters

Every list endpoint accepts `limit` and `offset` as query-string parameters. `limit` defaults to 10, may not be smaller than 1 and may not exceed 100; `offset` defaults to 0 and may not be negative. The four pagination fields reported in `meta` are `limit`, `offset`, `total_count` (the number of rows matching the filters before the window is applied) and `has_more` (true when rows remain beyond the current window).

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Two collections have a documented reading order worth stating explicitly: a route's segments are returned in `sequence_index` order, and a certificate's conditions are returned `created_at` ascending, which is the order in which the order's condition array supplied them.

Collections also accept domain filters, each of which narrows the result set by exact match on the named field:

- Projects: `stage`, `jurisdiction_state`.
- Planning studies: `project_id`, `status`.
- Alternatives: `study_id`, `kind`, `screening_status`.
- Routes: `project_id`, `kind`, `status`.
- Route segments: `route_id`, `survey_status`, `federal_permit_status`, `construction_state`.
- Public comments: `route_id`, `segment_id`, `commenter_landowner_id`, `materiality`, `status`.
- Applications: `project_id`, `study_id`, `proposed_route_id`, `review_status`, `record_status`.
- Hearing sessions: `application_id`, `kind`, `status`.
- Interventions: `application_id`, `landowner_id`, `status`, `petitioner_kind`.
- Certificates: `application_id`, `certified_route_id`, `status`, `posture`.
- Certificate conditions: `certificate_id`, `category`, `constraint_kind`, `status`.
- Easement tracts: `project_id`, `segment_id`, `landowner_id`, `acquisition_status`, `payment_status`.
- Construction activities: `certificate_id`, `segment_id`, `status`, `activity_kind`.
- Nonconformances: `certificate_id`, `condition_id`, `activity_id`, `severity`, `status`.

The scoped sub-collection reads — a project's planning studies and routes, a study's alternatives, a route's segments, an application's hearing sessions, a certificate's conditions — accept the same filters as their flat equivalents and are the intended way to traverse a reference in reverse.

### 2.4. Record Identity, Timestamps and Versioning

Every persisted resource carries four common properties. `id` is a server-minted UUID with no type prefix; clients never supply it. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that begins at 1 when the row is created and is incremented by exactly 1 on every mutation of that row, with `updated_at` refreshed at the same moment. Every entity in this system — projects, planning studies, alternatives, routes, route segments, public comments, siting applications, hearing sessions, interventions, certificates, certificate conditions, landowners, easement tracts, construction activities and nonconformances — carries all four.

Because `version` is the currency of the concurrency rules in §2.7, three docket operations are called out explicitly: accepting or returning a filing as deficient, closing the evidentiary record, and accepting an amendment each increment the application's `version` by 1. Likewise, extending an easement offer increments the tract's `version` by 1. Cascades count as mutations: when a certificate's posture changes and that change suspends activities and halts segments, each touched row's `version` advances and its `updated_at` is refreshed.

Only the `Landowner` record carries no lifecycle state at all — it is a pure directory row holding `name`, `email` and `mailing_address`, and exists so that comments, intervention petitions and easement tracts can point at a legally identified owner.

### 2.5. Path Resolution and Referential Consistency

URL path identifiers are resolved strictly left to right. On a nested read such as a project's routes, the project is resolved first; if it does not exist the response is `ERR_RESOURCE_NOT_FOUND` (HTTP 404) and the rest of the path is never examined. The same code covers any unresolvable path identifier on any endpoint.

References supplied inside a request body are resolved separately and report `ERR_REFERENCE_NOT_FOUND` (HTTP 404). This covers `project_id`, `study_id`, `route_id`, `segment_id`, `landowner_id`, `application_id`, `certificate_id`, `condition_id`, `activity_id` and `certified_route_id` wherever a write endpoint accepts them.

Resolving is not the same as belonging. Several cross-aggregate rules additionally check that a resolved row sits in the right family, and these are reported with distinct codes at HTTP 422: a comment's segment must belong to the route named in the same payload and an application's route must belong to the named project (`ERR_ROUTE_PROJECT_MISMATCH`, which guards both comment intake and application filing); an application's study and proposed route must both belong to its project (`ERR_STUDY_PROJECT_MISMATCH`); an easement tract's segment must sit on a route belonging to the tract's own project (`ERR_TRACT_SEGMENT_MISMATCH`); a construction activity's segment must sit on the certificate's certified route (`ERR_SEGMENT_ROUTE_MISMATCH`); and a nonconformance's condition — and its activity, when one is named — must belong to the certificate it is filed against (`ERR_CONDITION_CERTIFICATE_MISMATCH`).

### 2.6. The Logical Clock and Statutory Windows

Nothing in this system reads the wall clock. All time-dependent behaviour — comment windows, decision deadlines, hearing eligibility, seasonal blackout evaluation, payment rescission windows and every `_at` timestamp the server mints — resolves against a **logical clock**. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. An administrative test-driving capability sets the clock to a supplied `current_utc` instant and is available to all roles; it returns HTTP 200 and no payload.

Statutory arithmetic on that clock is deliberately plain. Adding a comment window of `comment_window_days` days, a filing period of 365 days, a statutory suspension of `suspension_days` days, or the 30-day rescission window means adding that many whole days to the reference instant. Slack between two instants is measured in whole days, truncated toward zero, with both instants read as UTC.

### 2.7. Superseding Writes on Tracts and Dockets

Two write operations legitimately overwrite work a client may not have seen, and both are therefore protected by optimistic concurrency control.

Extending or re-extending a negotiated easement offer requires the request to carry `expected_tract_version`, a mandatory field holding the client's last observed `version` of the target easement tract. A new offer supersedes the standing one and recomputes the offered compensation at the next escalation factor, so a client working from an out-of-date view of the tract would silently replace an offer it never read. If `expected_tract_version` does not equal the tract's current `version`, the request is rejected with `ERR_STALE_TRACT_VERSION` (HTTP 412) and nothing is written.

Filing an amendment to a deficient application requires the request to carry `expected_application_version`, a mandatory field holding the client's last observed `version` of the target application. An amendment supersedes the deficient filing, resets the filing instant and recomputes the statutory decision deadline, so a client working from an out-of-date view of the docket would restart a clock it never read. If `expected_application_version` does not equal the application's current `version`, the request is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412) and nothing is written.

No other endpoint takes a version field, and no other endpoint performs a version check. Both stale-version rejections are evaluated after authentication, authorization, existence and shape checks but before any state-machine or business rule, so a stale write against a row in the wrong state reports the stale version rather than the state problem.

### 2.8. Numeric Precision and Rounding Discipline

All monetary quantities are integers denominated in cents; field names ending in `_cents` are never fractional. Wherever a monetary result is derived from a multiplication or a division, it is rounded **half up to whole cents**. Ratios, scores and indices are rounded half up as well, to the number of decimal places the owning rule declares: constraint scores, densities and compliance indices to two decimal places; a study's levelized transmission cost to two decimal places; its benefit ratio and need margin ratio to four decimal places; an alternative's levelized cost to two decimal places; and a nonconformance's deduction to two decimal places.

Three disciplines about rounding *order* matter more than the rounding itself, because collapsing them changes answers by whole cents or hundredths of a point:

1. **Round then sum.** A route's constraint score is the sum of per-segment scores that were each already rounded to two decimal places — never the rounding of an unrounded sum. The project's committed easement total likewise sums per-tract values that were each already rounded.
2. **Intermediate results are frozen before they are reused.** Where a rule computes an intermediate figure and then divides or multiplies by it, the already-rounded intermediate is the operand, not the raw quotient.
3. **Thresholds are compared against rounded values.** A need margin ratio whose raw quotient is 1.149975 rounds to 1.1500 and therefore passes a threshold of 1.1500.

Threshold comparisons are stated inclusively or exclusively wherever they appear and should be read literally: "at least", "no more than", "strictly below" and "strictly after" all mean exactly what they say.

### 2.9. The Project Escrow Ledger

Each project carries a four-figure escrow ledger, all in cents and all server-maintained: `escrow_funded_cents` (everything the developer has ever deposited and not yet had released), `escrow_balance_cents` (undisbursed funds still available), `escrow_disbursed_cents` (funds already paid out to landowners) and `easement_committed_cents` (the roll-up of compensation the project has become liable for). A project is created with all four at zero.

A conservation invariant holds after every single operation: the funded total always equals the undisbursed balance plus the disbursed total. Depositing into escrow adds the deposited `amount_cents` to both the funded total and the balance, recording the client-supplied `reference` for audit. Disbursing compensation to a landowner moves value from balance to disbursed by the same amount; rescinding that disbursement moves it back. Certificate closeout releases whatever balance remains, setting the balance to zero and reducing the funded total by the released amount, which keeps the invariant intact because the disbursed total is untouched.

`easement_committed_cents` is a different kind of figure: it is not cash but exposure, and it is recomputed as the sum of `committed_cents` over the project's easement tracts whose `acquisition_status` is `AGREED` or `AWARDED`. Tracts sitting at `NOT_STARTED`, `OFFERED`, `REJECTED` or `CONDEMNATION_FILED` contribute nothing, and a tract's payment state is irrelevant to the roll-up — a tract that is `AGREED` but unpaid still counts in full.

### 2.10. Segregation of Duties on the Record

Three separations of duty are enforced against the operator identifiers described in §2.1, and all three report at HTTP 403.

The developer who authored a planning study may not certify its own sufficiency: if the acting `X-User-ID` equals the study's `authored_by_user_id`, certification is refused with `ERR_SELF_CERTIFICATION`. The same code and the same comparison guard application filing — the developer who files an application must not be the `authored_by_user_id` of the study the filing relies on. That is two distinct operations sharing one error code.

On the commission side, the staff user who records the decision must not have presided over the hearing: if the acting `X-User-ID` matches the `presiding_user_id` of any hearing session on that application whose status is `HELD`, the decision is refused with `ERR_DECIDER_PRESIDED`. Sessions still in `SCHEDULED` status do not disqualify anyone.

### 2.11. Order of Rejection

Many operations in this domain can fail several ways at once, and clients depend on which failure surfaces. Checks are therefore evaluated in a fixed global order, and the first failure ends the request. From earliest to latest:

1. Header presence — `ERR_UNAUTHENTICATED`.
2. Role recognition and endpoint authorization — `ERR_UNAUTHORIZED`.
3. Path identifier resolution, left to right — `ERR_RESOURCE_NOT_FOUND`.
4. Body reference resolution — `ERR_REFERENCE_NOT_FOUND`.
5. Payload shape: required fields present, enum values inside their declared domains, numeric ranges honoured, conditional-field pairings satisfied — `ERR_INVALID_REQUEST`.
6. Landowner ownership of the tract or comment being acted on — `ERR_NOT_RESOURCE_OWNER`.
7. Stale-version rejection — `ERR_STALE_TRACT_VERSION` or `ERR_STALE_APPLICATION_VERSION`.
8. Terminal-state rejection: the targeted dimension is already in a terminal state — `ERR_TERMINAL_STATE`. This is checked **before** the general transition-existence check below.
9. Transition existence: no transition of the requested kind leaves the row's current state — `ERR_INVALID_STATE`.
10. Prerequisite-record states, in this internal order: study sufficiency (`ERR_STUDY_NOT_SUFFICIENT`), then the group comprising route publication status (`ERR_ROUTE_NOT_PUBLISHED`), route nomination status (`ERR_ROUTE_NOT_NOMINATED`), record closure (`ERR_RECORD_NOT_CLOSED`), outstanding scheduled hearings (`ERR_HEARING_STILL_SCHEDULED`) and hearing session earliness (`ERR_SESSION_NOT_STARTED`), then unruled interventions (`ERR_INTERVENTION_UNRULED`) alongside certificate revocation (`ERR_CERTIFICATE_REVOKED`), and finally certificate posture (`ERR_CERTIFICATE_NOT_ACTIVE`).
11. Safety rules: seasonal blackout (`ERR_SEASONAL_BLACKOUT_VIOLATION`) first, then the federal crossing rules (`ERR_FEDERAL_PERMIT_MISSING` and `ERR_FEDERAL_AGENCY_MISMATCH`), then the segregation-of-duties rules of §2.10 (`ERR_SELF_CERTIFICATION`, `ERR_DECIDER_PRESIDED`).
12. Structural business constraints: hearing window conflicts, crew capacity, duplicate segment sequence, sequence gaps, refinement/amendment/offer round caps and duplicate applications.
13. Temporal windows: comment window closed, comment window still open, rescission window expired.
14. Cross-family belonging: first the segment/route family checks (`ERR_SEGMENT_ROUTE_MISMATCH`, `ERR_TRACT_SEGMENT_MISMATCH`, `ERR_ROUTE_PROJECT_MISMATCH`), then the study and condition family checks (`ERR_STUDY_PROJECT_MISMATCH`, `ERR_CONDITION_CERTIFICATE_MISMATCH`).
15. Selector and eligibility rules: empty selector pools (`ERR_NO_NONTRANSMISSION_ALTERNATIVE`, `ERR_NO_REFINEMENT_TARGET`), zero deliverable capability, eminent-domain authority, and absence of value diminution.
16. Computed-threshold rules, in this internal order: constraint density, screened-in alternative count, right-of-way hold and easement acquisition first; then open-house coverage and cumulative compliance; then outstanding material comments and incomplete segments; then open nonconformances.
17. Fiscal rules last: filing fee sufficiency, escrow balance sufficiency and escrow funding sufficiency — and, at the very end, the requirement that an application snapshot at least one nominated alternate route.

Where two checks share a tier, the narrative in §3 names the order that applies to the specific operation.

### 2.12. Cascade Propagation and Derived Counters

Nothing in this system is edited by the client after creation; state advances through named operations, and each one propagates. Six derived counters are maintained by the server and are never client-supplied:

- A study's `alternatives_screened_in_count` is the number of alternatives on that study whose `screening_status` is `SCREENED_IN`.
- A route's `segment_count` is the number of segments on it, `total_miles` is the sum of their `miles` rounded half up to two decimal places, and `unsurveyed_segment_count` is the number of its segments whose `survey_status` is `DESKTOP`.
- A segment's `material_comment_count` is the number of public comments naming that segment whose `materiality` is `MATERIAL` and whose `status` is still `RECEIVED`.
- A segment's `committed_crew_count` is the sum of `crew_count` over the activities on that segment whose `status` is `SCHEDULED`, `IN_PROGRESS` or `SUSPENDED`. A suspended activity keeps occupying its crew slots.
- An application's `party_count` is the number of intervention petitions on it whose `status` is `GRANTED`.
- A route's `open_house_held_count` is the number of open houses recorded against it, and `open_house_counties` is the list of distinct county strings from those open houses in insertion order.

Cascades travel in one direction: from the finding or ruling that caused them outward to the certificate, then to activities, then to segments, then to the project. A certificate posture change suspends activities and halts their segments; a federal permit denial suspends activities on the denied segment; an activity reaching a terminal outcome can bubble its segment to completion; a granted second intervention lengthens the statutory clock and can flip the project's schedule posture and right-of-way hold. Each such propagation is described in §3 at the point where it originates.

## 3. Business Logic & Workflows

### 3.1. Establishing the Need Case

Everything begins with a **project**, created by a `Developer` with a `name`, a `voltage_class` of `KV_138`, `KV_345` or `KV_500`, a two-letter `jurisdiction_state` naming the siting commission with authority, and a contractual `target_energization_at` in-service instant. A new project opens in `stage` `PLANNING`, with `schedule_posture` `ON_TRACK`, `right_of_way_hold` false and all four escrow figures at zero. The stage dimension advances only forward, through `ROUTING`, `APPLICATION_FILED`, `CERTIFICATED`, `CONSTRUCTION` and finally the terminal `ENERGIZED`.

A `Developer` funds the mitigation and right-of-way escrow at any time by depositing an `amount_cents` with a `reference` string, per the ledger mechanics of §2.9. Funding is not gated on stage — developers routinely pre-fund before the order lands — but §3.9 shows why an under-funded escrow blocks construction.

The need case itself lives in a **planning study**, authored by a `Developer` against a `project_id`. A study declares its planning `horizon_year`, the `reliability_deficit_mw` of unserved capability the line must relieve (which must be strictly greater than zero), the `transmission_capex_cents` capital cost of the wires solution, and the `benefit_pv_cents` present value of the reliability and congestion benefits it would deliver. The study opens in `status` `DRAFT` and the acting user is recorded as its `authored_by_user_id`. Its four computed figures — `transmission_levelized_cents_per_mw`, `benefit_ratio`, `need_margin_ratio` and `selected_nta_alternative_id` — are all null until sufficiency certification runs, as is `certified_by_user_id`.

Against a study, either a `RouteAnalyst` or a `Developer` registers **alternatives**: each carries a `study_id`, a `kind` of `TRANSMISSION`, `NON_TRANSMISSION` or `HYBRID`, a narrative `description`, its `capex_cents` and the `deliverable_mw` capability it would provide. At creation the server freezes `levelized_cost_cents_per_mw` as the capital cost divided by the delivered capability, rounded half up to two decimal places; that figure is never recomputed afterwards. Because the division must exist, a `deliverable_mw` of zero or below is refused with `ERR_ZERO_DELIVERABLE` (HTTP 422). Alternatives open at `screening_status` `SUBMITTED` with a null `screen_reason`.

A `RouteAnalyst` then screens each alternative, supplying a `decision` of `SCREEN_IN` or `SCREEN_OUT` together with a `screen_reason` recording the analyst's rationale. Screening in moves the alternative `SUBMITTED → SCREENED_IN` and increments the parent study's screened-in count; screening out moves it `SUBMITTED → SCREENED_OUT`, which is terminal, and an alternative already screened in may still be screened out later along `SCREENED_IN → SCREENED_OUT`, which decrements the count. Screening in or out of `SUBMITTED` requires the parent study to be in `DRAFT`, `ALTERNATIVES_ANALYZED` or `INSUFFICIENT`; reversing a `SCREENED_IN` alternative requires only that the parent study is not yet `CERTIFIED_SUFFICIENT`.

Screening in has a second, quieter effect: it bubbles the study forward. The first screened-in alternative carries a study from `DRAFT → ALTERNATIVES_ANALYZED`, and a further screen-in against a study sitting at `INSUFFICIENT` carries it back `INSUFFICIENT → ALTERNATIVES_ANALYZED`. That second path also wipes the stale arithmetic: `need_margin_ratio`, `benefit_ratio`, `transmission_levelized_cents_per_mw`, `selected_nta_alternative_id` and `certified_by_user_id` all revert to null, because the analysis that produced them no longer describes the candidate set. A study may cycle through analysis and certification as many times as it takes to land at the terminal `CERTIFIED_SUFFICIENT`.

**Sufficiency certification** is the gate, and it is performed by a `Developer` other than the author, who submits an `attestation_note`. Its checks run in this order: first the self-certification bar of §2.10; then the requirement that the non-wires candidate pool be non-empty, reported as `ERR_NO_NONTRANSMISSION_ALTERNATIVE` (HTTP 422); then the requirement that the study have at least two screened-in alternatives of any kind, reported as `ERR_INSUFFICIENT_ALTERNATIVES` (HTTP 422). A study that is not sitting at `ALTERNATIVES_ANALYZED` cannot be certified at all.

The arithmetic proceeds in five steps and its result is data-determined, not client-selected. First, the transmission solution's unit cost is the study's transmission capital cost divided by its reliability deficit, rounded half up to two decimal places, and stored as `transmission_levelized_cents_per_mw`. Second, `benefit_ratio` is the benefit present value divided by the transmission capital cost, rounded half up to four decimal places. Third, the selector identifies the hardest non-wires competitor: eligible candidates are the alternatives on this study whose `kind` is `NON_TRANSMISSION` or `HYBRID` **and** whose `screening_status` is `SCREENED_IN`; alternatives of `kind` `TRANSMISSION`, and any alternative still `SUBMITTED` or already `SCREENED_OUT`, are excluded from the pool even though screened-in transmission alternatives still count toward the two-alternative gate. Candidates are ranked by `levelized_cost_cents_per_mw` ascending — cheapest first — with ties broken by earliest `created_at`; the winner's identifier is stored as `selected_nta_alternative_id`. If the pool is empty the certification is refused with `ERR_NO_NONTRANSMISSION_ALTERNATIVE` and the study remains at `ALTERNATIVES_ANALYZED`. Fourth, `need_margin_ratio` is the selected candidate's levelized cost divided by the study's already-rounded `transmission_levelized_cents_per_mw`, that quotient then multiplied by the already-rounded `benefit_ratio`, and the product rounded half up to four decimal places. Fifth, the threshold is applied to that rounded four-decimal ratio: a value of at least 1.1500 certifies the study, and anything below it does not.

Both outcomes are successful requests returning HTTP 201. A ratio at or above the threshold moves the study `ALTERNATIVES_ANALYZED → CERTIFIED_SUFFICIENT`; a ratio below it moves the study `ALTERNATIVES_ANALYZED → INSUFFICIENT`. In either direction all three ratios and the selected alternative identifier are computed and stored, and the acting user is recorded as `certified_by_user_id`.

### 3.2. Drawing Corridors: Routes, Segments and the Constraint Score

A **route** is created on a project by a `RouteAnalyst` or a `Developer` with a `project_id`, a human-readable `label` such as "Route A — river crossing", and a `kind` of either `PROPOSED` or `ALTERNATE`. Routes open in `status` `DRAFT` and travel through `CONSTRAINT_MAPPED`, `PUBLISHED_FOR_COMMENT`, `REFINING` and `NOMINATED` before reaching one of the two terminal outcomes, `CERTIFIED` or `REJECTED`. Creating the first route on a project also carries the project `PLANNING → ROUTING`, provided at least one planning study on that project has reached `CERTIFIED_SUFFICIENT`; where no study has yet been certified the route is still created and the project simply stays in `PLANNING`.

Segments are the unit of analysis. A `RouteAnalyst` adds each **route segment** with its `route_id`, a one-based `sequence_index` giving its position along the corridor, its length in `miles` (strictly positive), the `county` it crosses, a `crew_capacity` giving the maximum peak crew the segment can host across overlapping activity windows (zero or more), and four constraint criteria ratings — `land_use_rating`, `environmental_rating`, `cultural_rating` and `engineering_rating` — each an integer from 0 through 5 inclusive. Three optional flags round out the payload: `survey_status`, which is `DESKTOP` by default and may be supplied as `FIELD_VERIFIED`; `habitat_blackout`, false by default, marking the segment as carrying the sensitive-habitat flag; and `federal_crossing_kind`, `NONE` by default and otherwise `PUBLIC_LAND`, `NAVIGABLE_WATERWAY` or `WETLAND`. A `sequence_index` already used on the same route is refused with `ERR_SEGMENT_SEQUENCE_DUPLICATE` (HTTP 409).

New segments open with `construction_state` `PENDING` and a zero `committed_crew_count`, `material_comment_count` and `refinement_count`. Their `federal_permit_status` is initialised from the crossing kind: `NOT_REQUIRED` when the crossing kind is `NONE`, and `REQUIRED` otherwise. `federal_permit_agency` is null until a permit application records one. Adding a segment refreshes the parent route's `segment_count`, `total_miles` and `unsurveyed_segment_count`.

**Constraint mapping** is the `RouteAnalyst` operation that turns segment ratings into a route-level score, and it is the same operation whether it is run for the first time on a `DRAFT` route, re-run on a route already at `CONSTRAINT_MAPPED` to fold in segment edits, or run to bring a route back `REFINING → CONSTRAINT_MAPPED` after a refinement cycle. All three carry the same preconditions and all three land the route at `CONSTRAINT_MAPPED`, and every run refreshes the route's `segment_count`, `total_miles`, `unsurveyed_segment_count`, `constraint_score_preliminary`, `constraint_score_certified` and `constraint_density_certified` from current segment data; an optional `mapping_note` may accompany the request. Mapping requires at least two segments whose `sequence_index` values form a contiguous run from 1 to N with no gaps and no holes; anything else is refused with `ERR_SEGMENT_SEQUENCE_GAP` (HTTP 422). Mapping is also refused with `ERR_INVALID_STATE` (HTTP 409) while any segment carrying a federal crossing sits at `federal_permit_status` `DENIED` — a corridor with a refused crossing permit is not a mappable corridor.

The score itself is a weighted, mileage-scaled, voltage-adjusted sum, and it is computed **twice** on every mapping run. Start from the project's voltage multiplier: 1.00 for `KV_138`, 1.15 for `KV_345`, and 1.30 for `KV_500`. Then walk the route's segments in ascending `sequence_index` order — every segment on the route participates, with no filter on state, so segments added while the route was still a draft count in full. For each segment, form a base rating by multiplying the effective land-use rating by 0.25, the effective environmental rating by 0.35, the effective cultural rating by 0.25 and the effective engineering rating by 0.15, and adding those four products together. Cap that base rating at 4.50 per segment — the cap is applied to the base before mileage enters, never afterwards. Multiply the capped base by the segment's `miles` and then by the voltage multiplier, and round the result half up to two decimal places to obtain the segment's score. The route's score is the sum of those already-rounded segment scores; summing first and rounding once is a different and incorrect answer. Separately, `total_miles` is the sum of segment mileage rounded half up to two decimal places.

The two variants differ only in which ratings count as "effective". The **preliminary** variant, stored as `constraint_score_preliminary`, is the desk-study view used to compare candidate corridors internally: it uses every segment's four stored ratings verbatim, whatever the segment's survey status. The **certified** variant, stored as `constraint_score_certified`, is the filing-grade view: for any segment whose `survey_status` is `DESKTOP`, the environmental and cultural ratings are replaced by the worst-case value 5, while the land-use and engineering ratings are still taken verbatim; segments whose `survey_status` is `FIELD_VERIFIED` use their stored ratings unchanged. The two variants therefore coincide only when every segment on the route has been field-verified. Both are null until the first mapping run.

Only the certified variant feeds the gate. `constraint_density_certified` is the certified score divided by `total_miles`, rounded half up to two decimal places, and a route may be nominated only when that density is no greater than 4.00.

### 3.3. Federal Crossings

Wherever a corridor crosses federal land or navigable water, a `FederalPermitOfficer` drives the segment's permit dimension by recording an `action` of `APPLY`, `ISSUE` or `DENY`, optionally with an `agency` and a `determination_note`. Applying moves a segment `REQUIRED → APPLIED` and records the supplied agency as `federal_permit_agency`, which must be `BLM`, `USACE` or `USFS`. The agency must fit the crossing: a `PUBLIC_LAND` crossing may be handled by either `BLM` or `USFS`, a `NAVIGABLE_WATERWAY` crossing only by `USACE`, and a `WETLAND` crossing only by `USACE`. A mismatched agency, or any permit action against a segment whose `federal_crossing_kind` is `NONE`, is refused with `ERR_FEDERAL_AGENCY_MISMATCH` (HTTP 422).

From `APPLIED`, issuing the permit moves the segment to the terminal `ISSUED`, and denying it moves the segment to `DENIED`. A denial is a cascade origin: every construction activity on that segment whose status is `SCHEDULED` or `IN_PROGRESS` is moved to `SUSPENDED` with `suspension_reason` recorded as `FEDERAL_PERMIT_DENIED`, and the segment's `committed_crew_count` is deliberately left unchanged, because a suspended activity still occupies its crew slots. A segment whose construction state was `ACTIVE` when the denial landed is moved to `HALTED`. A denial is not the end of the road: after redesign, a further application carries the segment `DENIED → APPLIED` and records the agency again, so the permit cycle may run as many times as the redesign takes. `NOT_REQUIRED` and `ISSUED` are the two terminal resting places of this dimension.

### 3.4. Public Involvement: Publication, Open Houses, Comments and Refinement

A `Developer` **publishes** a corridor for public comment by supplying `comment_window_days`, an integer from 30 through 90 inclusive. Publication moves the route `CONSTRAINT_MAPPED → PUBLISHED_FOR_COMMENT` and sets `comment_window_closes_at` to the logical clock reading plus that many days. Publication is available only to routes whose `kind` is `PROPOSED` and only once a certified constraint score exists — the whole point of publishing is to publish a scored corridor. Alternate routes are never published; §3.5 explains why their nomination path is shorter.

Alongside publication, the `Developer` records each **open house** actually held, naming the `county` it was held in and the `attendee_count`, with an optional `held_at` instant. Each record increments `open_house_held_count`, and the county is appended to `open_house_counties` when it is not already present there — which is what makes "two open houses in two different counties" a meaningful test rather than a formality.

**Comment intake** is open to a `Landowner`, a `RouteAnalyst` or `CommissionStaff`. A comment names the `route_id` it concerns, a `commenter_kind` of `LANDOWNER`, `AGENCY` or `PUBLIC`, a `commenter_name` for display, the comment `body`, and a `materiality` of `MATERIAL` or `GENERAL`. It may name a `segment_id`, and a `MATERIAL` comment **must** name one — a comment that claims to be material without pointing at a specific segment is refused as a malformed payload with `ERR_INVALID_REQUEST` (HTTP 400). `commenter_landowner_id` is required exactly when the commenter kind is `LANDOWNER` and must be null otherwise. Comments open at `status` `RECEIVED` with a null `disposition_note`, and `received_at` is stamped from the logical clock. A material comment increments the named segment's `material_comment_count`.

Intake is bounded on both sides. The route must be published for comment or in refinement — intake against a route in any other status is refused with `ERR_ROUTE_NOT_PUBLISHED` (HTTP 409) — and the window must still be open: once the logical clock reaches or passes `comment_window_closes_at`, intake is refused with `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422). For a landowner commenting on their own behalf, the ownership check of §2.1 runs first; the named segment's membership of the named route is checked last, after the window check, and reports `ERR_ROUTE_PROJECT_MISMATCH`.

A `RouteAnalyst` **dispositions** each comment with a `disposition` of `ACKNOWLEDGE` or `DISMISS` and a written `disposition_note`. Acknowledging moves a comment `RECEIVED → ACKNOWLEDGED`; dismissing moves it `RECEIVED → DISMISSED` or `ACKNOWLEDGED → DISMISSED`. Both dispositions require the parent route to be in `PUBLISHED_FOR_COMMENT` or `REFINING`. Disposing of a `MATERIAL` comment out of `RECEIVED` decrements the named segment's material comment count, which is how an analyst clears the nomination blocker by answering comments rather than by redesigning. `INCORPORATED` and `DISMISSED` are the terminal statuses of a comment.

**Refinement** is the redesign path, driven by a `RouteAnalyst` with a `refinement_note`. It carries the route `PUBLISHED_FOR_COMMENT → REFINING` and is bounded by a hard cap of three completed cycles: a route whose `refinement_round` has already reached 3 is refused with `ERR_REFINEMENT_LIMIT_REACHED` (HTTP 409). Refinement requires a published or refining route, so an attempt against a route in another status reports `ERR_ROUTE_NOT_PUBLISHED`.

The refinement selector picks exactly one target. Eligible candidates are the segments on the route whose `material_comment_count` is at least 1. Candidates are ranked by material comment count descending, then by `environmental_rating` descending, with ties broken by lowest `sequence_index`. If no segment carries a material comment, the refinement is refused with `ERR_NO_REFINEMENT_TARGET` (HTTP 409), the route stays at `PUBLISHED_FOR_COMMENT` and `refinement_round` is not incremented. When a target is found, its identifier is stored on the route as `refinement_target_segment_id`; the target's `survey_status` is upgraded to `FIELD_VERIFIED` and its `refinement_count` is incremented; every public comment naming that segment whose status is `RECEIVED` or `ACKNOWLEDGED` is moved to `INCORPORATED`, after which the segment's material comment count is recomputed and therefore falls to zero; and the route's `refinement_round` is incremented. The route then sits at `REFINING` until a fresh constraint mapping run brings it back to `CONSTRAINT_MAPPED` — and because the target segment is now field-verified, that re-mapping is exactly the mechanism by which survey upgrades work their way into the certified score. The full cycle `PUBLISHED_FOR_COMMENT → REFINING → CONSTRAINT_MAPPED → PUBLISHED_FOR_COMMENT` may run at most three times.

### 3.5. Nomination and the Filing

**Nomination** is a `Developer` action with an optional `nomination_note`, and its gates depend entirely on route kind — this is the one place where proposed and alternate corridors are treated differently.

A `PROPOSED` route is nominated out of `PUBLISHED_FOR_COMMENT`, and four gates apply, evaluated in this order. First, the comment window must have closed: while the logical clock is still short of `comment_window_closes_at`, nomination is refused with `ERR_COMMENT_WINDOW_OPEN` (HTTP 422). Second, `constraint_density_certified` must be no greater than 4.00, or the request is refused with `ERR_CONSTRAINT_DENSITY_EXCEEDED` (HTTP 422). Third, the route must have at least two recorded open houses spanning at least two distinct counties, or the request is refused with `ERR_OPEN_HOUSE_COVERAGE_INSUFFICIENT` (HTTP 422). Fourth, no material comment may still be sitting at `RECEIVED`; any that are refuse the nomination with `ERR_MATERIAL_COMMENTS_OPEN` (HTTP 422). Clearing that last gate means either dispositioning the comments or refining the route to incorporate them.

An `ALTERNATE` route is nominated out of `CONSTRAINT_MAPPED`, and only the density gate applies — the publication, comment-window, open-house and material-comment gates are all specific to proposed corridors. Either way, a successful nomination lands the route at `NOMINATED`.

**Filing the siting application** is the pivot of the whole workflow. A `Developer` files with a `project_id`, the `study_id` of the need case, the `proposed_route_id` of the corridor being sought, a commission-assigned `docket_number`, and a `filing_fee_cents` tender. The filing's checks run in the order §2.11 lays down, and for this endpoint that order matters a great deal: the study must be `CERTIFIED_SUFFICIENT` (`ERR_STUDY_NOT_SUFFICIENT`, HTTP 409); the proposed route must have `kind` `PROPOSED` and `status` `NOMINATED` (`ERR_ROUTE_NOT_NOMINATED`, HTTP 409); the filer must not be the study's author (`ERR_SELF_CERTIFICATION`, HTTP 403); the project must not already carry an application whose `review_status` is neither `GRANTED` nor `DENIED` (`ERR_DUPLICATE_APPLICATION`, HTTP 409); the route must belong to the named project (`ERR_ROUTE_PROJECT_MISMATCH`, HTTP 422); the study and proposed route must both belong to that project (`ERR_STUDY_PROJECT_MISMATCH`, HTTP 422); the tendered fee must be at least twenty-five thousand dollars expressed in cents, that is 2,500,000 cents, or the filing is refused with `ERR_FILING_FEE_INSUFFICIENT` (HTTP 402); and last of all, the project must offer at least one nominated alternate corridor to snapshot, or the filing is refused with `ERR_NO_ALTERNATE_ROUTE` (HTTP 422).

A successful filing snapshots `alternate_route_ids` as the identifiers of the routes on that project whose `kind` is `ALTERNATE` and whose `status` is `NOMINATED` — a frozen list, not a live query. The application opens with `review_status` `FILED` and `record_status` `NOT_OPENED`, `party_count` and `suspension_days` and `amendment_round` at zero, a null `deficiency_note`, `filed_at` stamped from the logical clock, and the acting user recorded as `filed_by_user_id`. `decision_deadline_at` is computed as the filing instant plus 365 days plus `suspension_days` — zero days of suspension at this point. The project moves `ROUTING → APPLICATION_FILED`, and its schedule posture and right-of-way hold are recomputed.

That recomputation is the project's early-warning system. `slack_days` is the number of whole days from the application's `decision_deadline_at` to the project's `target_energization_at`, truncated. Negative slack — a deadline that falls after the contractual in-service date — makes the posture `CRITICAL`; slack of fewer than 180 days makes it `AT_RISK`; anything else leaves it `ON_TRACK`. `right_of_way_hold` is true exactly when the posture is `AT_RISK` or `CRITICAL`, and false when it is `ON_TRACK`. The posture is derived from the project's most recently filed application whose `review_status` is not `DENIED`; a project with no application at all keeps `ON_TRACK` with no hold. Posture is recomputed at filing, at every accepted amendment, and whenever the application's statutory suspension changes.

### 3.6. The Commission Docket

The application carries two independent status dimensions, and they evolve on separate tracks: `review_status` tracks the merits of the filing and `record_status` tracks the evidentiary proceeding. Read them together.

`CommissionStaff` perform the **sufficiency review**, supplying an `outcome` of `ACCEPT` or `REJECT` and, for a rejection, a `deficiency_note`. Acceptance requires the application to hold at least one entry in its snapshot of alternate routes and a filing fee of at least 2,500,000 cents; it moves the application `FILED → ACCEPTED` on the review dimension and simultaneously `NOT_OPENED → SCHEDULING` on the record dimension, and it increments the application's `version` by 1. Rejection requires a `deficiency_note`, records it, moves the application `FILED → DEFICIENT`, and likewise increments `version` by 1.

A `Developer` responds to a deficiency with an **amendment**, supplying the mandatory `expected_application_version` of §2.7, an `amendment_summary` and optionally a revised `filing_fee_cents`. An amendment is capped: an application whose `amendment_round` has already reached 2 is refused with `ERR_AMENDMENT_LIMIT_REACHED` (HTTP 409). A successful amendment increments `amendment_round`, clears `deficiency_note` back to null, moves the application `DEFICIENT → FILED`, resets `filed_at` to the current logical clock reading and recomputes `decision_deadline_at` from it, recomputes the project's schedule posture and right-of-way hold, and increments `version` by 1. The `FILED → DEFICIENT → FILED` cycle may therefore run at most twice.

A `HearingExaminer` **schedules hearing sessions** against an `application_id`, each with a `kind` of `PREHEARING`, `EVIDENTIARY` or `PUBLIC_TESTIMONY` and a `window_start_at` and `window_end_at`, where the end must fall strictly after the start. Sessions open at `status` `SCHEDULED`, with `exhibits_admitted_count` at zero and the acting examiner recorded as `presiding_user_id`. Sessions on the same application may not crowd one another: take the new session's closed interval and pad it by two hours on each side — that is, from 120 minutes before its start to 120 minutes after its end — and compare that padded interval against the unpadded closed interval of every existing session on the same application whose status is `SCHEDULED` or `HELD`. If those two closed intervals intersect at any point, including when they merely touch at an endpoint, the new session is refused with `ERR_HEARING_WINDOW_CONFLICT` (HTTP 409).

**Holding** a session is also the examiner's act, and it records the `exhibits_admitted_count` admitted into the record, moving the session `SCHEDULED → HELD` — the terminal status of that dimension. A session may not be held before the logical clock reaches its `window_start_at`; earlier attempts are refused with `ERR_SESSION_NOT_STARTED` (HTTP 409). Holding requires the application's record dimension to be at `SCHEDULING`, `EVIDENTIARY_REQUIRED` or `RECORD_OPEN`.

Holding a session is what opens the record, but with a guard. From `SCHEDULING`, holding a session of any kind moves the record `SCHEDULING → RECORD_OPEN`. From `EVIDENTIARY_REQUIRED`, only an `EVIDENTIARY` session opens the record — holding a `PREHEARING` or `PUBLIC_TESTIMONY` session while the record sits at `EVIDENTIARY_REQUIRED` leaves the record exactly where it was.

**Intervention petitions** may be filed by a `Landowner` or by `CommissionStaff` on an `application_id`, declaring a `petitioner_kind` of `LANDOWNER` or `INTEREST_GROUP` and the `grounds` asserting the petitioner's interest. The two petitioner kinds are strictly polymorphic: a `LANDOWNER` petition must carry a `landowner_id` and must leave `organization_name` null, while an `INTEREST_GROUP` petition must carry an `organization_name` and must leave `landowner_id` null. Violating either pairing is `ERR_INVALID_REQUEST` (HTTP 400). Petitions open at `status` `PETITIONED` with a null `ruling_reason` and `ruled_by_user_id`, and `filed_at` stamped from the logical clock.

`CommissionStaff` **rule** on each petition with a `ruling` of `GRANT` or `DENY` plus a `ruling_reason`, and the acting user is recorded as `ruled_by_user_id`. Granting requires the record dimension to be at `SCHEDULING`, `EVIDENTIARY_REQUIRED` or `RECORD_OPEN`; it moves the petition `PETITIONED → GRANTED` and increments the application's `party_count`. Denying requires a reason and moves the petition `PETITIONED → DENIED`. Both are terminal.

The second granted petition is the docket's most consequential cascade. When a grant brings `party_count` to two or more while the record sits at `SCHEDULING`, the record advances `SCHEDULING → EVIDENTIARY_REQUIRED`, `suspension_days` is set to 90, `decision_deadline_at` is recomputed as the filing instant plus 365 days plus those 90 suspension days, and the project's `schedule_posture` and `right_of_way_hold` are recomputed from the lengthened deadline. A contested docket can therefore flip a project to `AT_RISK` and freeze its condemnation programme without anyone touching the project directly.

**Record closure** is the examiner's final act, taking an optional `closure_note`, and it moves the record `RECORD_OPEN → RECORD_CLOSED`, incrementing the application's `version` by 1. Two prerequisites guard it, in this order: no session on the application may still be at `SCHEDULED` (`ERR_HEARING_STILL_SCHEDULED`, HTTP 409), and every intervention petition on the application must have been ruled either `GRANTED` or `DENIED` (`ERR_INTERVENTION_UNRULED`, HTTP 409). `RECORD_CLOSED` is terminal.

### 3.7. The Order, the Certificate and its Conditions

`CommissionStaff` record the commission's **decision** with an `outcome` of `GRANT` or `DENY`. Either outcome requires the application to be sitting at `ACCEPTED` on the review dimension and at `RECORD_CLOSED` on the record dimension; a decision attempted before the record closes is refused with `ERR_RECORD_NOT_CLOSED` (HTTP 409). Either outcome is also subject to the separation of §2.10 — a staff user who presided over any `HELD` session on that application is refused with `ERR_DECIDER_PRESIDED`.

A denial moves the application `ACCEPTED → DENIED` and sweeps the corridor slate clean: every route on the project still at `NOMINATED` moves to the terminal `REJECTED`.

A grant is richer. It carries a `certified_route_id`, which must name either the application's proposed route or one of the routes in its alternate snapshot; a boolean `eminent_domain_authorized` recording whether the order confers condemnation authority; a `mitigation_base_cents` figure fixing the mitigation commitment; and `conditions`, an ordered array of condition objects. The grant moves the application `ACCEPTED → GRANTED`, mints a **certificate** with `status` `ISSUED` and `posture` `ACTIVE`, records the acting user as `issued_by_user_id` and stamps `issued_at` from the logical clock, sets both compliance indices to 100, moves the named route `NOMINATED → CERTIFIED`, moves every other `NOMINATED` route on the project to `REJECTED`, and carries the project `APPLICATION_FILED → CERTIFICATED`.

Each element of the `conditions` array becomes a **certificate condition** row, created in array order so that the certificate's conditions read back in the order the order imposed them. A condition carries a `code` such as `ENV-BLACKOUT-1`; a `category` of `ENVIRONMENTAL`, `CULTURAL`, `LAND_USE`, `ENGINEERING` or `PUBLIC_SAFETY`; a `constraint_kind` of `SEASONAL_BLACKOUT`, `CREW_LIMIT`, `NOTICE` or `MONITORING`; and a `severity_weight` from 1 through 5 inclusive, which both multiplies nonconformance deductions and drives the escrow surcharge. Seasonal blackout conditions carry an inclusive `blackout_start_mmdd` and `blackout_end_mmdd` calendar range in month-day form and nothing else; crew limit conditions carry a `crew_limit` giving the maximum peak crew the order permits per segment across overlapping activity windows and nothing else. All conditions open at `status` `ACTIVE` with a null `waiver_reason`.

The **mitigation escrow requirement** is computed once, at issuance, and frozen — and its evaluation order is pinned, because reordering the steps produces a different answer on identical inputs. First, select `escrow_tier` from `mitigation_base_cents` **alone**: a base below five million dollars, that is below 500,000,000 cents, is `TIER_1`; a base below twenty million dollars, that is below 2,000,000,000 cents, is `TIER_2`; anything at or above that is `TIER_3`. Second, take the tier's contingency rate — 0.10 for `TIER_1`, 0.14 for `TIER_2`, 0.18 for `TIER_3` — multiply it by the mitigation base and only the mitigation base, and round half up to whole cents to obtain `contingency_cents`. Third, count the conditions created with this order whose `severity_weight` is 4 or greater, and set `condition_surcharge_cents` to twenty-five thousand dollars — 2,500,000 cents — per such heavy condition. Fourth, `escrow_required_cents` is the mitigation base plus the contingency plus the surcharge. Applying the contingency rate to the base plus surcharge, or re-deriving the tier from a running total, are both wrong. None of these four figures is ever recomputed after issuance.

`CommissionStaff` may **waive** a condition on the record, supplying a `waiver_reason`. A waiver moves the condition `ACTIVE → WAIVED`, which is terminal, and it requires the condition to be currently `ACTIVE` and the certificate's posture not to be `REVOKED` — a waiver against a revoked certificate is refused with `ERR_CERTIFICATE_REVOKED` (HTTP 409), and a waiver against a certificate whose posture is not `ACTIVE` is refused with `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP 409). A waived condition stops constraining construction scheduling from that moment forward: it no longer blocks activity windows and no longer contributes a crew ceiling. It does **not** rewrite the money — `condition_surcharge_cents` and `escrow_required_cents` stay exactly as the order fixed them, because the escrow requirement is a snapshot of the order and not a running tally. Nor does it erase history: findings already recorded against a waived condition continue to weigh on both compliance indices.

### 3.8. Easement Acquisition: Negotiated Purchase and Eminent Domain

A landowner of record is registered by a `Developer` or by `CommissionStaff` with a `name`, a notice `email` and a statutory `mailing_address`.

An **easement tract** is created by a `Developer` against a `project_id`, the `segment_id` of the segment it burdens, the `landowner_id` of its owner, and the county's `parcel_number`. Its valuation inputs come in two families that serve the two acquisition paths. The negotiated family is `acres` (strictly positive), `per_acre_value_cents` giving the appraised fee value per acre, `easement_factor` giving the fraction of fee value the easement takes (strictly greater than zero and no more than 1), and an optional `structure_damages_cents` for structures and improvements, defaulting to zero. The condemnation family is the whole-property `before_value_cents` and `after_value_cents`, plus an optional `severance_damages_cents` defaulting to zero. A tract opens at `acquisition_status` `NOT_STARTED`, `payment_status` `UNPAID`, `offer_round` zero, `paid_amount_cents` zero and `committed_cents` zero, with `offered_compensation_cents`, `agreed_compensation_cents`, `award_cents`, `paid_at`, `court_docket_number` and `deposit_cents` all null. The tract's segment must belong to a route on the tract's own project, or the creation is refused with `ERR_TRACT_SEGMENT_MISMATCH` (HTTP 422).

The tract carries two independent dimensions. `acquisition_status` runs `NOT_STARTED`, `OFFERED`, `AGREED`, `REJECTED`, `CONDEMNATION_FILED` and `AWARDED`, with `AGREED` and `AWARDED` as its terminal resting places. `payment_status` runs `UNPAID`, `PAID` and `RESCINDED` with no terminal state, and it moves entirely independently of the acquisition track.

A `Developer` **extends an offer**, supplying the mandatory `expected_tract_version` of §2.7 and an optional `offer_note`. Offers are capped at three: a tract whose `offer_round` has already reached 3 is refused with `ERR_OFFER_LIMIT_REACHED` (HTTP 409). An offer also requires the project's certificate to be `ISSUED` with a posture other than `REVOKED`; an offer against a revoked certificate is refused with `ERR_CERTIFICATE_REVOKED`. A successful offer increments `offer_round`, recomputes `offered_compensation_cents`, moves the tract `NOT_STARTED → OFFERED` or, for a sweetened re-offer, `REJECTED → OFFERED`, and increments the tract's `version` by 1.

The **negotiated offer** valuation values the easement interest and nothing else, and its two roundings are separate on purpose. First, multiply `acres` by `per_acre_value_cents` and then by `easement_factor`, and round that land value half up to whole cents. Then add `structure_damages_cents` to the rounded land value to obtain the base offer. Then apply the escalation factor for the round just entered — 1.00 for the first offer, 1.05 for the second, 1.12 for the third — multiplying it by the already-rounded base offer, and round that product half up to whole cents to obtain `offered_compensation_cents`. Collapsing the two roundings into a single final rounding changes the answer by a cent on fractional-acre tracts. The negotiated path ignores the whole-property before and after values, severance damages and any court deposit entirely.

The `Landowner` — and it must be the tract's own landowner, per §2.1 — **responds** with a `response` of `ACCEPT` or `REJECT` and an optional `response_note`, and may only do so while the tract sits at `OFFERED`. Accepting freezes `agreed_compensation_cents` as a copy of the standing `offered_compensation_cents`, sets `committed_cents` to that agreed figure, moves the tract `OFFERED → AGREED`, and triggers a recomputation of the project's `easement_committed_cents` roll-up. Rejecting simply moves the tract `OFFERED → REJECTED`, leaving the door open to a sweetened offer or to condemnation.

**Condemnation** is filed by a `Developer` out of `REJECTED`, supplying the `court_docket_number` and the `deposit_cents` paid into court with the petition. It has three gates. The certificate must confer eminent-domain authority and at least two offers must already have been extended — that is, `offer_round` must be at least 2 — or the filing is refused with `ERR_EMINENT_DOMAIN_NOT_AUTHORIZED` (HTTP 403). The project must not carry a right-of-way hold: a project whose `right_of_way_hold` is true refuses the filing with `ERR_RIGHT_OF_WAY_HOLD` (HTTP 409), which is how a slipping schedule freezes the condemnation programme. And the certificate must not be revoked. A successful filing records the docket number and deposit and moves the tract `REJECTED → CONDEMNATION_FILED`.

`CommissionStaff` **record the court's award**, optionally with an `award_note`, moving the tract `CONDEMNATION_FILED → AWARDED`. The **condemnation award** valuation is a genuinely different measure of the same taking. The whole-property diminution is `before_value_cents` minus `after_value_cents`, and that difference must be strictly positive — an award recorded where the before value does not exceed the after value is refused with `ERR_NO_VALUE_DIMINUTION` (HTTP 422). Statutory interest on the court deposit is `deposit_cents` multiplied by the statutory rate of 0.06, rounded half up to whole cents. `award_cents` is the diminution plus `severance_damages_cents` plus that deposit interest. The condemnation measure ignores `acres`, `per_acre_value_cents`, `easement_factor`, `structure_damages_cents` and `offer_round` entirely, so on identical tract data the award and the last offer will diverge — that divergence is the point, not a defect. Recording the award sets `committed_cents` to `award_cents` and recomputes the project's committed roll-up.

**Payment** is a `Developer` action carrying a `payment_reference`. It requires the tract to be at `AGREED` or `AWARDED` on the acquisition track, and it requires the project's `escrow_balance_cents` to be at least the tract's `committed_cents`; a shortfall is refused with `ERR_ESCROW_INSUFFICIENT` (HTTP 402). A payment sets `paid_amount_cents` to the committed figure, stamps `paid_at` from the logical clock, decreases the project's escrow balance and increases its disbursed total by that same amount, and moves the tract `UNPAID → PAID`.

`CommissionStaff` may **rescind** a disbursement with a `rescission_reason`, but only inside the statutory window: rescission is permitted while the logical clock is strictly earlier than 30 days after `paid_at`, and at or beyond that point it is refused with `ERR_RESCISSION_WINDOW_EXPIRED` (HTTP 422). Rescission zeroes `paid_amount_cents`, restores the project's escrow balance and reduces its disbursed total by the rescinded amount, and moves the tract `PAID → RESCINDED`. A rescinded tract can be paid again — `RESCINDED → PAID` runs the same checks and debits the escrow ledger afresh — and the conservation invariant of §2.9 must hold after every step of that cycle. Note that neither payment nor rescission touches `easement_committed_cents`, which tracks commitment rather than cash.

### 3.9. Construction and Compliance Monitoring

A `Developer` **schedules a construction activity** against a `certificate_id` and a `segment_id`, declaring an `activity_kind` of `CLEARING`, `FOUNDATION` or `STRINGING`, the `crew_count` committed for the whole window (at least 1), and the window itself as `window_start_at` and `window_end_at`, where the end must fall strictly after the start. The occupation window is **half-open**: it includes its start instant and excludes its end instant, so one activity ending exactly when another begins does not overlap it. Activities open at `status` `SCHEDULED` with a null `suspension_reason`, `started_at` and `completed_at`, and the segment's `committed_crew_count` grows by the declared crew count immediately.

Scheduling runs four checks in this order. The certificate's posture must be `ACTIVE`, or the request is refused with `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP 409). Then the seasonal restriction: if the segment's `habitat_blackout` flag is set and the activity's window touches any calendar day inside the inclusive month-day range of an `ACTIVE` `SEASONAL_BLACKOUT` condition on that certificate, the activity is refused with `ERR_SEASONAL_BLACKOUT_VIOLATION` (HTTP 422). Both endpoints of the blackout range are inside the restriction, and a range whose end month-day falls earlier in the calendar than its start month-day wraps across the year boundary. Conditions that have been `WAIVED` impose no blackout at all, and a segment without the habitat flag is never blacked out. Then the crew ceiling: form the effective limit as the smaller of the segment's `crew_capacity` and the lowest `crew_limit` among the `ACTIVE` `CREW_LIMIT` conditions on the certificate — where the certificate carries no active crew-limit condition, the segment's own capacity is the whole limit. Sum the `crew_count` of every activity on that same segment whose half-open window intersects the new one and whose status is `SCHEDULED`, `IN_PROGRESS` or `SUSPENDED`, add the new activity's crew count, and refuse the request with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422) if that total exceeds the effective limit. Touching windows do not intersect and therefore do not contend. Finally, the segment must belong to the certificate's `certified_route_id`, or the request is refused with `ERR_SEGMENT_ROUTE_MISMATCH` (HTTP 422).

**Starting** an activity — with an optional `start_note` — is where the whole system's couplings converge, and the checks fire in this order. The certificate's posture must be `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`). The logical clock must have reached the activity's `window_start_at`; an early start is refused with `ERR_INVALID_STATE` (HTTP 409). The segment's `federal_permit_status` must be either `NOT_REQUIRED` or `ISSUED`; a status of `REQUIRED`, `APPLIED` or `DENIED` refuses the start with `ERR_FEDERAL_PERMIT_MISSING` (HTTP 422). Every easement tract on that segment must be at `AGREED` or `AWARDED`, and at least one such tract must exist — a segment with no tract at all, or with any tract short of acquisition, refuses the start with `ERR_EASEMENT_NOT_ACQUIRED` (HTTP 422). And the project's `escrow_funded_cents` must be at least the certificate's `escrow_required_cents`, or the start is refused with `ERR_ESCROW_UNDERFUNDED` (HTTP 402).

A successful start moves the activity `SCHEDULED → IN_PROGRESS`, stamping `started_at` from the logical clock on the first start, and carries the segment `PENDING → ACTIVE` on its construction dimension. The first activity started anywhere on the project also carries the project `CERTIFICATED → CONSTRUCTION`. The same operation restarts a suspended activity: `SUSPENDED → IN_PROGRESS` clears `suspension_reason`, returns the segment to `ACTIVE` — including the recovery `HALTED → ACTIVE` — and requires posture `ACTIVE`, a permit at `NOT_REQUIRED` or `ISSUED`, and a logical clock at or past the window start.

**Completion** — with an optional `completion_note` — moves an activity `IN_PROGRESS → COMPLETE`, stamps `completed_at`, and reduces the segment's `committed_crew_count` by that activity's crew count. It is refused with `ERR_OPEN_NONCONFORMANCE` (HTTP 409) while any nonconformance referencing that activity is still `OPEN`. When completion leaves no activity on the segment at `SCHEDULED`, `IN_PROGRESS` or `SUSPENDED`, and at least one activity on the segment reached `COMPLETE`, the segment bubbles `ACTIVE → COMPLETE` and its `committed_crew_count` is set to zero. `COMPLETE` is terminal for both dimensions.

**Cancellation** — carrying a `cancellation_reason` — moves an activity `SCHEDULED → CANCELLED` or `SUSPENDED → CANCELLED` and releases the segment's committed crew by that activity's crew count. A cancellation can itself be the event that empties the segment's live work queue, and the same bubbling rule then applies: once every activity on the segment has reached `COMPLETE` or `CANCELLED` and at least one of them reached `COMPLETE`, the segment moves `ACTIVE → COMPLETE` with its committed crew count set to zero. A segment on which every activity was cancelled and none completed stays at `ACTIVE`. `COMPLETE` and `CANCELLED` are the activity's two terminal statuses.

A `ComplianceMonitor` **files a nonconformance** against a `certificate_id` and a `condition_id`, with a `severity` of `MINOR`, `MAJOR` or `SEVERE` and the monitor's field `observation`. An `activity_id` may be named for a finding tied to a specific activity, and is left null for programme-level findings. The named condition must belong to the named certificate, and a named activity must belong to the same certificate, or the filing is refused with `ERR_CONDITION_CERTIFICATE_MISMATCH` (HTTP 422). Findings open at `status` `OPEN` with a null `corrective_action` and `observed_at` stamped from the logical clock, and the referenced condition moves `ACTIVE → VIOLATED`.

Each finding's `deduction_points` is frozen at creation. Start from the severity's base points — 4 for `MINOR`, 12 for `MAJOR`, 30 for `SEVERE` — then scale it by a weighting factor built from the condition's `severity_weight`: subtract 1 from that weight, multiply the remainder by 0.2, add 1, and multiply the base points by the result. Round half up to two decimal places. A `MINOR` finding on a weight-1 condition therefore deducts its base points unscaled, while the same finding on a weight-5 condition deducts nearly double.

Both compliance indices are then recomputed from the certificate's whole finding history. Each index is 100 minus the sum of the effective deductions of the findings on that certificate whose status is `OPEN` or `CORRECTED`, rounded half up to two decimal places and floored at zero — a negative index is reported as 0.00. Findings that were `VOIDED` are excluded from both indices. Findings against conditions that have since been `WAIVED` still count in full, because a waiver stops future enforcement without erasing recorded history. The two indices differ only in how they treat a corrected finding. In the **rolling** index, an `OPEN` finding contributes its full deduction and a `CORRECTED` finding contributes half of it, so correcting a finding restores half its penalty. In the **cumulative** index, both `OPEN` and `CORRECTED` findings contribute their full deduction, so a correction restores nothing. The two figures are identical until the first correction and diverge permanently thereafter.

Posture is derived after **both** indices have been refreshed, and in this order: if `compliance_index_cumulative` is strictly below 25.00 the posture is `REVOKED`; otherwise, if `compliance_index_rolling` is strictly below 60.00 the posture is `STOP_WORK`; otherwise it is `ACTIVE`. The thresholds are strict, so a rolling index of exactly 60.00 stays `ACTIVE` and a cumulative index of exactly 25.00 stays out of `REVOKED`.

Posture changes cascade outward. A finding that drives the rolling index below 60.00 while the cumulative index holds at 25.00 or above moves the certificate `ACTIVE → STOP_WORK`, suspends every activity on that certificate whose status is `SCHEDULED` or `IN_PROGRESS` with `suspension_reason` recorded as `CERTIFICATE_STOP_WORK`, and moves each affected segment `ACTIVE → HALTED` on its construction dimension. A finding that drives the cumulative index below 25.00 moves the certificate to the terminal `REVOKED` — from `ACTIVE` or from `STOP_WORK` alike — suspends every non-terminal activity on the certificate with a recorded suspension reason, and halts the affected segments. Suspended activities keep their crew slots throughout.

Recovery is asymmetric by design. A `ComplianceMonitor` **records corrective action** with a `corrective_action` note, moving a finding `OPEN → CORRECTED`; the rolling index is recomputed with that finding's deduction halved, the cumulative index is recomputed unchanged, and if the correction was the last `OPEN` finding on its condition the condition returns `VIOLATED → ACTIVE`. `CommissionStaff` may instead **void** a finding by submitting the same operation with `void_finding` set to true, moving it `OPEN → VOIDED`; both indices are then recomputed with the finding removed entirely. Either path may lift the certificate `STOP_WORK → ACTIVE`, which requires the cumulative index to be at 25.00 or above — but the suspended activities do not resume on their own; each must be individually restarted. Because the cumulative index never recovers, a certificate that has once been revoked stays revoked. `CORRECTED` and `VOIDED` are the finding's terminal statuses.

**Closeout** is the last act, performed by `CommissionStaff` with an optional `closeout_note`. Its four gates fire in this order: the certificate's posture must be `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`, HTTP 409); `compliance_index_cumulative` must be at least 75.00 (`ERR_COMPLIANCE_TOO_LOW`, HTTP 422); every segment on the certified route must have reached `construction_state` `COMPLETE` (`ERR_SEGMENTS_INCOMPLETE`, HTTP 409); and no nonconformance on the certificate may still be `OPEN` (`ERR_OPEN_NONCONFORMANCE`, HTTP 409). A successful closeout moves the certificate `ISSUED → CLOSED`, carries the project `CONSTRUCTION → ENERGIZED`, and releases the remaining escrow — the project's `escrow_balance_cents` is set to zero and `escrow_funded_cents` is reduced by the released amount, leaving the disbursed total untouched so that the conservation invariant still holds. `CLOSED` and `ENERGIZED` are both terminal.

## 4. Endpoint Definitions

Every write operation in this API is expressed as a creation — of a resource, or of an event recorded against a resource — and therefore returns `201 Created` on success, returning the affected resource in `data`. That includes state-transition operations such as nomination, holding a hearing, recording a decision or correcting a finding, each of which returns the resource it advanced. Read operations return `200 OK`. The one exception is the administrative clock capability, which returns `200 OK` with an empty `data` object. All paths below are absolute.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/siting/projects` | List transmission projects | All roles |
| GET | `/siting/projects/{projectId}` | Read one project with its escrow ledger and schedule posture | All roles |
| GET | `/siting/projects/{projectId}/planning-studies` | List the planning studies on a project | All roles |
| GET | `/siting/projects/{projectId}/routes` | List the routes on a project | All roles |
| GET | `/siting/planning-studies` | List planning studies across projects | All roles |
| GET | `/siting/planning-studies/{studyId}` | Read one planning study with its computed need ratios | All roles |
| GET | `/siting/planning-studies/{studyId}/alternatives` | List the alternatives on a study | All roles |
| GET | `/siting/alternatives` | List alternatives across studies | All roles |
| GET | `/siting/alternatives/{alternativeId}` | Read one alternative with its levelized cost | All roles |
| GET | `/siting/routes` | List routes across projects | All roles |
| GET | `/siting/routes/{routeId}` | Read one route with both constraint-score variants and the density gate value | All roles |
| GET | `/siting/routes/{routeId}/segments` | List the segments of a route in sequence order | All roles |
| GET | `/siting/route-segments` | List route segments | All roles |
| GET | `/siting/route-segments/{segmentId}` | Read one route segment with its permit, crew and comment counters | All roles |
| GET | `/siting/public-comments` | List public comments | All roles |
| GET | `/siting/public-comments/{commentId}` | Read one public comment | All roles |
| GET | `/siting/applications` | List siting applications | All roles |
| GET | `/siting/applications/{applicationId}` | Read one application with both status dimensions, party count and decision deadline | All roles |
| GET | `/siting/applications/{applicationId}/hearing-sessions` | List the hearing sessions on an application | All roles |
| GET | `/siting/hearing-sessions` | List hearing sessions | All roles |
| GET | `/siting/hearing-sessions/{sessionId}` | Read one hearing session | All roles |
| GET | `/siting/interventions` | List interventions | All roles |
| GET | `/siting/interventions/{interventionId}` | Read one intervention petition and its ruling | All roles |
| GET | `/siting/certificates` | List certificates | All roles |
| GET | `/siting/certificates/{certificateId}` | Read one certificate with its escrow requirement and both compliance indices | All roles |
| GET | `/siting/certificates/{certificateId}/conditions` | List the conditions attached to a certificate, in the order the order imposed them | All roles |
| GET | `/siting/certificate-conditions` | List certificate conditions | All roles |
| GET | `/siting/certificate-conditions/{conditionId}` | Read one certificate condition | All roles |
| GET | `/siting/landowners` | List landowners of record | All roles |
| GET | `/siting/landowners/{landownerId}` | Read one landowner | All roles |
| GET | `/siting/easement-tracts` | List easement tracts | All roles |
| GET | `/siting/easement-tracts/{tractId}` | Read one easement tract with both status dimensions and all compensation figures | All roles |
| GET | `/siting/construction-activities` | List construction activities | All roles |
| GET | `/siting/construction-activities/{activityId}` | Read one construction activity | All roles |
| GET | `/siting/nonconformances` | List nonconformances | All roles |
| GET | `/siting/nonconformances/{nonconformanceId}` | Read one nonconformance with its frozen deduction | All roles |
| POST | `/siting/projects` | Create a transmission project in stage PLANNING | Developer |
| POST | `/siting/projects/{projectId}/escrow-deposits` | Deposit funds into the project's mitigation/right-of-way escrow | Developer |
| POST | `/siting/planning-studies` | Create a planning study establishing the need case | Developer |
| POST | `/siting/planning-studies/{studyId}/sufficiency-certification` | Certify (or fail) the need case against the non-transmission alternative selector | Developer |
| POST | `/siting/alternatives` | Register an alternative, including non-transmission options, against a planning study | RouteAnalyst, Developer |
| POST | `/siting/alternatives/{alternativeId}/screening` | Screen an alternative in or out of the analysis | RouteAnalyst |
| POST | `/siting/routes` | Create a proposed or alternate route on a project | RouteAnalyst, Developer |
| POST | `/siting/route-segments` | Add a segment with its four constraint criteria ratings to a route | RouteAnalyst |
| POST | `/siting/route-segments/{segmentId}/federal-permit-actions` | Record a federal crossing permit action for public land or waterway crossings | FederalPermitOfficer |
| POST | `/siting/routes/{routeId}/constraint-mapping` | Run constraint mapping and compute both score variants and the density | RouteAnalyst |
| POST | `/siting/routes/{routeId}/publication` | Publish a proposed route for public comment and open the comment window | Developer |
| POST | `/siting/routes/{routeId}/open-houses` | Record a public open house held for a route in a named county | Developer |
| POST | `/siting/routes/{routeId}/refinements` | Refine the route in response to material comments | RouteAnalyst |
| POST | `/siting/routes/{routeId}/nomination` | Nominate a route for inclusion in the siting application | Developer |
| POST | `/siting/public-comments` | Intake a public comment on a published route | Landowner, RouteAnalyst, CommissionStaff |
| POST | `/siting/public-comments/{commentId}/disposition` | Acknowledge or dismiss a comment with a written disposition | RouteAnalyst |
| POST | `/siting/applications` | File the siting application, snapshotting the nominated alternate routes | Developer |
| POST | `/siting/applications/{applicationId}/sufficiency-review` | Accept the filing or return it as deficient | CommissionStaff |
| POST | `/siting/applications/{applicationId}/amendments` | Amend a deficient application, superseding the prior filing | Developer |
| POST | `/siting/hearing-sessions` | Schedule a prehearing, evidentiary or public-testimony session | HearingExaminer |
| POST | `/siting/hearing-sessions/{sessionId}/holding` | Record that a scheduled session was held and exhibits admitted | HearingExaminer |
| POST | `/siting/applications/{applicationId}/record-closure` | Close the evidentiary record | HearingExaminer |
| POST | `/siting/applications/{applicationId}/decision` | Issue the order granting (with certificate and conditions) or denying the application | CommissionStaff |
| POST | `/siting/interventions` | Petition to intervene as a landowner or interest group | Landowner, CommissionStaff |
| POST | `/siting/interventions/{interventionId}/ruling` | Rule on an intervention petition | CommissionStaff |
| POST | `/siting/certificate-conditions/{conditionId}/waiver` | Waive a certificate condition on the record | CommissionStaff |
| POST | `/siting/certificates/{certificateId}/closeout` | Close out the certificate after construction compliance is demonstrated | CommissionStaff |
| POST | `/siting/landowners` | Register a landowner of record | Developer, CommissionStaff |
| POST | `/siting/easement-tracts` | Create an easement tract on a certified route segment | Developer |
| POST | `/siting/easement-tracts/{tractId}/offers` | Extend or re-extend a negotiated purchase offer | Developer |
| POST | `/siting/easement-tracts/{tractId}/offer-response` | Accept or reject the standing offer | Landowner |
| POST | `/siting/easement-tracts/{tractId}/condemnation` | File an eminent domain proceeding where the certificate authorizes it | Developer |
| POST | `/siting/easement-tracts/{tractId}/award` | Record the court's just-compensation award | CommissionStaff |
| POST | `/siting/easement-tracts/{tractId}/payments` | Disburse the committed compensation to the landowner from project escrow | Developer |
| POST | `/siting/easement-tracts/{tractId}/payment-rescission` | Rescind a disbursement inside the statutory window and restore escrow | CommissionStaff |
| POST | `/siting/construction-activities` | Schedule a construction activity on a certified route segment | Developer |
| POST | `/siting/construction-activities/{activityId}/start` | Start, or restart after suspension, a construction activity | Developer |
| POST | `/siting/construction-activities/{activityId}/completion` | Complete a construction activity | Developer |
| POST | `/siting/construction-activities/{activityId}/cancellation` | Cancel a scheduled or suspended construction activity | Developer |
| POST | `/siting/nonconformances` | File a construction compliance nonconformance against a certificate condition | ComplianceMonitor |
| POST | `/siting/nonconformances/{nonconformanceId}/correction` | Record corrective action, or void the finding | ComplianceMonitor, CommissionStaff |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical UTC clock | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_STALE_TRACT_VERSION` | 412 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERMINAL_STATE` | 409 |
| `ERR_ROUTE_NOT_PUBLISHED` | 409 |
| `ERR_STUDY_NOT_SUFFICIENT` | 409 |
| `ERR_ROUTE_NOT_NOMINATED` | 409 |
| `ERR_RECORD_NOT_CLOSED` | 409 |
| `ERR_HEARING_STILL_SCHEDULED` | 409 |
| `ERR_INTERVENTION_UNRULED` | 409 |
| `ERR_SESSION_NOT_STARTED` | 409 |
| `ERR_CERTIFICATE_NOT_ACTIVE` | 409 |
| `ERR_CERTIFICATE_REVOKED` | 409 |
| `ERR_SEASONAL_BLACKOUT_VIOLATION` | 422 |
| `ERR_FEDERAL_PERMIT_MISSING` | 422 |
| `ERR_FEDERAL_AGENCY_MISMATCH` | 422 |
| `ERR_SELF_CERTIFICATION` | 403 |
| `ERR_DECIDER_PRESIDED` | 403 |
| `ERR_HEARING_WINDOW_CONFLICT` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 422 |
| `ERR_SEGMENT_SEQUENCE_DUPLICATE` | 409 |
| `ERR_SEGMENT_SEQUENCE_GAP` | 422 |
| `ERR_REFINEMENT_LIMIT_REACHED` | 409 |
| `ERR_AMENDMENT_LIMIT_REACHED` | 409 |
| `ERR_OFFER_LIMIT_REACHED` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_COMMENT_WINDOW_CLOSED` | 422 |
| `ERR_COMMENT_WINDOW_OPEN` | 422 |
| `ERR_RESCISSION_WINDOW_EXPIRED` | 422 |
| `ERR_CONDITION_CERTIFICATE_MISMATCH` | 422 |
| `ERR_SEGMENT_ROUTE_MISMATCH` | 422 |
| `ERR_TRACT_SEGMENT_MISMATCH` | 422 |
| `ERR_ROUTE_PROJECT_MISMATCH` | 422 |
| `ERR_STUDY_PROJECT_MISMATCH` | 422 |
| `ERR_CONSTRAINT_DENSITY_EXCEEDED` | 422 |
| `ERR_MATERIAL_COMMENTS_OPEN` | 422 |
| `ERR_OPEN_HOUSE_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_INSUFFICIENT_ALTERNATIVES` | 422 |
| `ERR_NO_NONTRANSMISSION_ALTERNATIVE` | 422 |
| `ERR_NO_REFINEMENT_TARGET` | 409 |
| `ERR_ZERO_DELIVERABLE` | 422 |
| `ERR_EMINENT_DOMAIN_NOT_AUTHORIZED` | 403 |
| `ERR_RIGHT_OF_WAY_HOLD` | 409 |
| `ERR_NO_VALUE_DIMINUTION` | 422 |
| `ERR_EASEMENT_NOT_ACQUIRED` | 422 |
| `ERR_OPEN_NONCONFORMANCE` | 409 |
| `ERR_SEGMENTS_INCOMPLETE` | 409 |
| `ERR_COMPLIANCE_TOO_LOW` | 422 |
| `ERR_FILING_FEE_INSUFFICIENT` | 402 |
| `ERR_NO_ALTERNATE_ROUTE` | 422 |
| `ERR_ESCROW_INSUFFICIENT` | 402 |
| `ERR_ESCROW_UNDERFUNDED` | 402 |

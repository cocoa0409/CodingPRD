# Regional Climate Adaptation & Resilience Planning API — Product Requirements Document

## 1. Introduction

A regional planning agency sits between the climate science that produces downscaled hazard projections and the member local governments that must actually build things. Its work product is a periodically updated regional adaptation plan: a ranked, funded, endorsed programme of capital projects that reduce heat, flood, drought and storm exposure across a shared landscape of water, power, transport, health and communications lifelines. Today that work is scattered across spreadsheets. Exposure projections live with the science team, vulnerability scoring lives with consultants, asset criticality rankings live in a GIS layer nobody dares refresh, benefit-cost analyses live in workbooks whose author also signs them off, and the endorsement vote that turns a draft into an adopted plan happens in a room with no audit trail. When the science is re-run at a higher resolution, nobody can say which analyses, which rankings, and which funding decisions have silently gone stale.

This document specifies the service that replaces that patchwork. The system is a single system of record mounted under `/resilience` that carries a hazard projection from draft through publication and republication, propagates the consequences of a republication all the way to an in-flight endorsement round, screens adaptation strategies on cost, co-benefit and feasibility, prices them through a pinned cost stack, subjects them to an independently certified benefit-cost analysis, allocates scarce capital against an equity floor, tracks implementation through periodic indicator reports, and negotiates mutual aid for shared lifeline assets across jurisdictional boundaries. Two design commitments run through all of it. First, **freshness is a first-class state**: a record that was computed against an input which has since moved does not quietly keep its number, it is marked stale and must be recomputed by a deliberate act. Second, **money and pledged units are conserved**: every allocation and every withdrawal, every commitment and every release, leaves the governing total exactly where it was.

The specification is written for engineers who will implement the service and for the analysts and delegates who will live inside it. It is deliberately explicit about evaluation order, rounding, and the exact boundary at which a threshold flips, because in this domain those details decide which projects get built. Where a rule looks like an accounting nicety — a floor instead of a round, a rate keyed on an intermediate value rather than a total, a half-open interval on one resource and a closed buffered interval on another — the rule is intentional and normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to any endpoint under `/resilience` must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting in. If either header is missing or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined. If both headers are present but `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 403). If the role is recognised but is not among the roles that the requested endpoint permits, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). These three checks run in exactly that order, so a caller sending a garbage role to an endpoint they would not be allowed to reach anyway sees `ERR_UNKNOWN_ROLE`, not `ERR_ROLE_NOT_PERMITTED`.

The six roles are `RegionalAdministrator`, `HazardAnalyst`, `ProjectSponsor`, `BCAReviewer`, `JurisdictionDelegate` and `EquityOfficer`. Their spellings are exact and case-sensitive.

- **`RegionalAdministrator`** — regional planning agency staff who run the plan cycle, the asset register and the capital program. When `X-User-Role` is `RegionalAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`.
- **`HazardAnalyst`** — climate science staff who own downscaled projections, vulnerability assessment and asset criticality ranking. When `X-User-Role` is `HazardAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- **`ProjectSponsor`** — the sponsoring jurisdiction's project manager, who proposes projects, links assets, prepares analyses and reports indicators. When `X-User-Role` is `ProjectSponsor`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks on any adaptation project compare the project's `jurisdiction_id` to `X-User-ID`, and a caller may only act on projects whose `jurisdiction_id` equals that value.
- **`BCAReviewer`** — the independent benefit-cost reviewer who certifies or rejects an analysis but never prepares one. When `X-User-Role` is `BCAReviewer`, `X-User-ID` is an opaque reviewer identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, but it does compare it against the `prepared_by_user_id` recorded on the analysis under review, as described in §2.10.
- **`JurisdictionDelegate`** — the member jurisdiction's delegate to the regional body, who runs engagement, casts weighted endorsements and negotiates mutual aid. When `X-User-Role` is `JurisdictionDelegate`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks compare `X-User-ID` to the `jurisdiction_id` of an endorsement, the `host_jurisdiction_id` of an engagement session or a mutual aid pact, and the `requesting_jurisdiction_id` of a mutual aid commitment.
- **`EquityOfficer`** — the regional equity officer who alone may waive a capital program's equity benefit floor for a specific project. When `X-User-Role` is `EquityOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

For the two entity-backed roles — `ProjectSponsor` and `JurisdictionDelegate` — a write whose target row belongs to a different jurisdiction than the one `X-User-ID` resolves to is rejected with `ERR_JURISDICTION_SCOPE_VIOLATION` (HTTP 403). Read access is deliberately broad: every retrieval endpoint in the system is open to all six roles, so an analyst can see the funding consequences of a republication and a delegate can see how a neighbour's assets were ranked.

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

Every endpoint that returns a collection is paginated by two optional query parameters. `limit` defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` defaults to 0 and may not be negative. Collections are always returned sorted by `created_at` in ascending order, so the oldest matching row appears first and a stable page walk is possible by holding `limit` fixed and advancing `offset`.

For every response whose `response_type` is `"array"`, the four pagination fields `limit`, `offset`, `total_count` and `has_more` are returned inside `meta` alongside `api_request_id` and `api_request_timestamp`. `total_count` counts every row matching the supplied filters across the whole collection, not merely the rows on the current page, and `has_more` is true exactly when rows matching the filters remain beyond the current page.

Collections also accept domain filters, all optional and all combinable with each other and with pagination. Member governments may be filtered by `status`, `svi_tier` and `disadvantaged_flag`. Plan cycles may be filtered by `status`. Hazard profiles accept `jurisdiction_id`, `hazard_type`, `scenario` and `status`. The lifeline asset register accepts `jurisdiction_id`, `upstream_asset_id`, `asset_class`, `criticality_status`, `criticality_tier` and `is_shared`. Vulnerability assessments accept `hazard_profile_id`, `asset_id`, `subject_type`, `method` and `status`. Adaptation projects accept `plan_cycle_id`, `jurisdiction_id`, `prerequisite_project_id`, `capital_program_id`, `hazard_type`, `strategy_type`, `screening_status`, `analysis_status`, `program_status` and `implementation_status`. Project-to-asset links accept `project_id`, `asset_id` and `benefit_reaches_disadvantaged`. Benefit-cost analyses accept `project_id`, `method`, `status` and `grant_eligible`. Capital programs accept `fiscal_year` and `funding_posture`. Engagement sessions accept `plan_cycle_id`, `host_jurisdiction_id`, `modality` and `status`. Endorsements accept `plan_cycle_id`, `jurisdiction_id`, `decision` and `round_number`. Mutual aid pacts accept `host_jurisdiction_id`, `resource_class` and `status`. Mutual aid commitments accept `pact_id`, `requesting_jurisdiction_id`, `asset_id` and `status`.

### 2.4. Record Identity, Revision Counters and the Logical Clock

Every persisted record carries an `id` that is a server-minted UUID with no type prefix and no embedded semantics; clients never supply it. Every record also carries a `created_at` timestamp, written once at creation, formatted as an ISO 8601 UTC instant with exactly three fractional digits (for example `2026-08-01T00:00:00.000Z`). Almost every record additionally carries an `updated_at` timestamp in the same format, refreshed on every mutation, and a `version` integer that starts at 1 when the record is created and increments by exactly 1 on every mutation that changes the record — including mutations the record's owner did not request, such as the freshness cascades described in §2.9.

There is one deliberate exception. A project-to-asset link is an immutable junction row: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified — a link is added, and its effects propagate outwards, but the link itself never changes.

All time in the system is read from a **logical clock**, never from the host machine's wall clock. The clock starts at `2026-08-01T00:00:00Z` when the server boots and never advances on its own. An administrative test-driving capability moves it: the request supplies the target instant as `to_iso8601`, and the response reports the resulting clock reading as `current_utc`. Every timestamp the server writes itself — `published_at`, `assessed_at`, `certified_at`, `adopted_at`, `grant_submitted_at`, `awarded_at`, `released_at`, `fulfilled_at`, `cast_at` — is the logical clock reading at the moment of the write. Every temporal comparison the system makes also reads the logical clock, including the expiry evaluation on a mutual aid pact and the `endorsement_deadline` on a plan cycle.

### 2.5. The Validation Ladder

Validation is a strictly ordered ladder, not a set of independent checks. Rules are evaluated in ascending priority order, and the **first** violated rule short-circuits the request: its error is returned and nothing at all is written, not even partially. Two requests that each violate two rules therefore report the lower-priority-number rule, and a caller repairing a payload may see a different error on each attempt as they climb the ladder. The ordering below is the top of that ladder; the domain rules that sit further down it are stated alongside the workflows they guard in §3, and every one of them names its own error code there.

1. **Authentication.** `X-User-Role` and `X-User-ID` must both be present and non-empty, or `ERR_UNAUTHENTICATED`.
2. **Role recognition.** `X-User-Role` must name one of the six declared roles, or `ERR_UNKNOWN_ROLE`.
3. **Role permission.** The supplied role must appear in the target endpoint's permitted role list, or `ERR_ROLE_NOT_PERMITTED`.
4. **Path existence, left to right.** Every identifier embedded in the URL must resolve to an existing row, and they are checked in the order they appear in the path from left to right, so on a nested path the leftmost unresolved identifier decides the error. An unresolved `jurisdiction_id` yields `ERR_JURISDICTION_NOT_FOUND`; `plan_cycle_id` yields `ERR_PLAN_CYCLE_NOT_FOUND`; `hazard_profile_id` yields `ERR_HAZARD_PROFILE_NOT_FOUND`; `asset_id` yields `ERR_ASSET_NOT_FOUND`; `assessment_id` yields `ERR_ASSESSMENT_NOT_FOUND`; `project_id` yields `ERR_PROJECT_NOT_FOUND`; `link_id` yields `ERR_LINK_NOT_FOUND`; `analysis_id` yields `ERR_ANALYSIS_NOT_FOUND`; `program_id` yields `ERR_PROGRAM_NOT_FOUND`; `session_id` yields `ERR_SESSION_NOT_FOUND`; `endorsement_id` yields `ERR_ENDORSEMENT_NOT_FOUND`; `pact_id` yields `ERR_PACT_NOT_FOUND`; and `commitment_id` yields `ERR_COMMITMENT_NOT_FOUND`. All thirteen are HTTP 404.
5. **Body reference existence, in declared field order.** Every foreign reference carried in a request payload must resolve, checked in the order the endpoint declares its input fields, using the same identifier-to-code map as the path check. A body `jurisdiction_id`, `host_jurisdiction_id` or `requesting_jurisdiction_id` that does not resolve yields `ERR_JURISDICTION_NOT_FOUND`; a body `asset_id` or `upstream_asset_id` yields `ERR_ASSET_NOT_FOUND`; a body `project_id` or `prerequisite_project_id` yields `ERR_PROJECT_NOT_FOUND`; a body `hazard_profile_id` yields `ERR_HAZARD_PROFILE_NOT_FOUND`.
6. **Jurisdictional ownership.** For the two entity-backed roles, the `Jurisdiction` bound to `X-User-ID` must own the target row, or `ERR_JURISDICTION_SCOPE_VIOLATION`. For a `ProjectSponsor` the owned field is the target adaptation project's `jurisdiction_id`. For a `JurisdictionDelegate` it is the endorsement's `jurisdiction_id`, the engagement session's `host_jurisdiction_id`, the mutual aid pact's `host_jurisdiction_id`, or the mutual aid commitment's `requesting_jurisdiction_id`, whichever the endpoint targets.
7. **Payload shape.** Every write endpoint validates its payload shape and rejects a violation with `ERR_INVALID_REQUEST` (HTTP 422). All required input fields must be present; every enum-valued field must carry a declared member of its enumeration; every decimal score whose domain is zero through one must lie inside that range; every amount in cents, every unit count and every basis-point integer must be non-negative; `service_life_years` must be at least 1; `discount_rate_bps` must lie between 0 and 2000 inclusive; `quorum_weight_bps` must lie between 1 and 10000 inclusive; `cobenefit_points` must lie between 0 and 20 inclusive; and `horizon_year` must be one of 2040, 2060 or 2080.
8. **Window ordering.** Wherever a payload carries a `window_start` and a `window_end` — scheduling an engagement session, creating a mutual aid pact, and creating a mutual aid commitment — `window_start` must be strictly earlier than `window_end`, or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422). All three of those operations are subject to this rule.

Everything from priority 9 downwards is domain logic: jurisdiction standing, plan-cycle state, publication state, freshness state, concurrency, segregation of duties, equity floors, graph acyclicity, uniqueness, cross-entity readiness, arithmetic sanity, temporal occupancy and fiscal capacity — in that broad order. §3 states each of those rules where the workflow it guards is described, and §2.7 through §2.10 state the cross-cutting ones. The relative order within each workflow is stated explicitly wherever more than one rule can fire on the same call.

### 2.6. Decimal Discipline, Basis Points and Rounding

Money is always an integer number of cents; there are no fractional cents anywhere in the system and no floating-point money. Shares and rates are expressed in **basis points** — hundredths of a percent, so 10000 basis points is the whole of something and 6600 basis points is sixty-six percent. Scores are `Decimal` values, never binary floats, and every comparison against a threshold is an exact decimal comparison.

Two rounding disciplines coexist and must not be confused. Values that represent a *magnitude* are rounded **half up**: a value exactly halfway between two representable results rounds away from zero. Social vulnerability, exposure, sensitivity, adaptive capacity, redundancy and feasibility inputs carry 2 fractional digits; `annual_event_probability` carries 4. Computed magnitudes are rounded half up to their declared precision — `vulnerability_score` and `consequence_score` to 2 fractional digits, `indicator_attainment_pct` to 2, and `screen_score`, `bcr` and `priority_score` to 4. Money computed from a rate is rounded half up to whole cents.

Values that represent a *share in basis points*, by contrast, are always **floored** — truncated toward zero, never rounded up. That applies to `equity_benefit_share_bps`, `equity_achieved_bps`, `equity_reach_bps` and `achieved_weight_bps`, and to the halving of conditioned endorsement weight described in §3.8. A share that works out to 61.53 percent is 6153 basis points and never 6154.

One further rule governs every threshold in the document: **the band is read off the rounded value, never the unrounded one.** A score is clamped where a clamp applies, then rounded to its declared precision, and only then compared against its floors. All floors in this system are inclusive unless the text says otherwise, so a value landing exactly on a floor falls in the higher band.

### 2.7. Optimistic Concurrency on the Two Shared Ledgers

Two operations read a shared running total and write it back, and both are therefore protected by optimistic concurrency control. In each case the write request must carry the version the client last observed on the parent record, and the server compares that value against the parent's stored `version` **before** it evaluates any capacity or ledger rule.

Allocating capital to a project reads a capital program's `available_cents` and writes back `committed_cents`, `available_cents`, `equity_committed_cents`, `equity_achieved_bps` and `funding_posture`. The allocation request must therefore supply `expected_capital_program_version`, which is not optional. If it does not equal the target `CapitalProgram`'s current `version` — because some other writer advanced the program since the client read it — the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412) and no ledger field is touched. On success the program's `version` increments by 1, which means replaying the identical request with the same expected version is rejected on the second call.

Committing units against a mutual aid pact reads the pact's `free_units` and its existing commitment windows to evaluate peak overlap load, then writes `reserved_units`, `free_units` and the pact's `status`. The commitment request must therefore supply `expected_mutual_aid_pact_version`, also non-optional. A value that does not equal the `MutualAidPact`'s current `version` is rejected with `ERR_STALE_PACT_VERSION` (HTTP 412) before capacity is evaluated at all. On success the pact's `version` increments by 1.

No other endpoint in the system takes a version field. Only these two operations require one, and supplying one elsewhere has no meaning.

### 2.8. Conservation of Capital and of Pledged Aid Units

Two quantities in this system are conserved, and the invariant that expresses each is checked after every mutation that could disturb it.

For a capital program, the conserved quantity is `authorized_cents`. After every allocation and after every withdrawal, `committed_cents` plus `available_cents` equals `authorized_cents` exactly. The ledger is never adjusted incrementally by a delta; it is recomputed from scratch over the surviving set of committed projects, which is why a withdrawal cannot leave drift behind. `available_cents` is defined as `authorized_cents` minus `committed_cents` and is never stored independently of that relationship.

For a mutual aid pact, the conserved quantity is `pledged_units`. After every commitment, every release and every fulfilment, `reserved_units` plus `free_units` equals `pledged_units` exactly, with `free_units` defined as `pledged_units` minus `reserved_units`. Because a commitment is only ever admitted when the resulting peak load stays within the pledge, `reserved_units` always lies between zero and `pledged_units` and `free_units` is never negative.

### 2.9. Freshness, Cascades and Derived-State Propagation

The system's central discipline is that a computed value is only trustworthy while the inputs it was computed from have not moved. Rather than recompute silently, the system marks the dependent record **stale** and requires a deliberate recomputation. Two cascades implement this, and both are transitive: each hop is caused by the previous hop's mutation, never directly by the originating request.

The first is the **hazard republication cascade**, five hops deep. Republishing a downscaled projection changes the exposure term; because the projection's publication counter advanced, the vulnerability assessments computed against the older counter become stale; because those assessments became stale, the lifeline assets they ranked lose their ranking outputs and require recomputation; because those assets require recomputation, the certified benefit-cost analyses that depend on them become stale and their projects' analysis dimension follows; and because those projects' analyses became stale, any plan cycle currently in an open endorsement round is pushed back into revision or, if its revision budget is spent, fails outright. §3.2 states each hop in full, including which fields are retained and which are nulled.

The second is the **withdrawal compensation cascade**, four hops deep, which exactly reverses an allocation with no ledger drift. §3.7 states it in full.

Every row a cascade touches has its `updated_at` refreshed and its `version` incremented by 1, exactly as if a client had modified it directly. This matters in two ways. First, a client holding an old `version` of a capital program or a mutual aid pact will find its next write rejected on the concurrency check in §2.7. Second, a cascade that touches many rows increments many versions, and callers that cache derived state must re-read.

### 2.10. Segregation of Duties and the Equity Waiver

Three duties in this system are deliberately held by three different parties, and the separation is enforced by the server, not by convention.

The user who **prepares** a benefit-cost analysis may never **certify or reject** it. When an analysis is created, the acting user's `X-User-ID` is recorded on the analysis as `prepared_by_user_id`. When a reviewer later certifies or rejects that analysis, the server compares the reviewer's `X-User-ID` against `prepared_by_user_id`; if they are equal the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule applies equally to certification and to rejection — a preparer cannot self-clear an analysis by rejecting it either. On a successful certification the reviewer's identifier is recorded as `certified_by_user_id`.

The party who may **waive the equity floor** is a third role again, `EquityOfficer`, which can neither prepare nor certify an analysis and cannot allocate capital. Only that role may set a project's `equity_waiver_granted`, and the waiver request must carry a `waiver_rationale` explaining it.

Finally, capital **allocation** is reserved to `RegionalAdministrator` while analysis **preparation** belongs to `ProjectSponsor`, so no single actor can both price a project and fund it.

## 3. Business Logic & Workflows

### 3.1. Member Jurisdictions and the Social Vulnerability Overlay

The register of member local governments is the foundation everything else rests on. A `RegionalAdministrator` admits a member by supplying its display `name`, its agency-assigned `jurisdiction_code`, its resident `population`, its `svi_score`, and the `endorsement_weight` that member will carry in plan endorsement tallies; `status` may also be supplied and defaults to `ACTIVE` when omitted. The `name` must be a non-blank string of 1 to 120 characters. The `jurisdiction_code` must be 3 to 32 characters long and may contain only uppercase letters, digits and hyphens, and it must be unique across the whole register — admitting a second member with a code another member already holds is rejected with `ERR_DUPLICATE_JURISDICTION_CODE`. `population` must be at least 1, because it serves as the social-vulnerability denominator. `svi_score` is a decimal with 2 fractional digits between 0.00 and 1.00 inclusive. `endorsement_weight` must lie between 1 and 10 inclusive and defaults to 1. `status` is one of `ACTIVE`, `PROBATION` or `SUSPENDED`.

Two fields are never supplied by the client. On creation, and again on any subsequent amendment that supplies a new `svi_score`, the server derives the banded `svi_tier` from that score and the boolean `disadvantaged_flag` from the tier. The banding is: `SEVERE` when the score is at least 0.75; `HIGH` when the score is at least 0.50 but below 0.75; `MODERATE` when the score is at least 0.25 but below 0.50; and `LOW` otherwise. Each floor is inclusive, so a score of exactly 0.50 lands in `HIGH` and a score of exactly 0.25 lands in `MODERATE`, while 0.24 falls to `LOW` and 0.75 rises to `SEVERE`. The comparisons are exact decimal comparisons and never float comparisons. `disadvantaged_flag` is true exactly when `svi_tier` is `HIGH` or `SEVERE`, and false for `MODERATE` and `LOW` — that single boolean is what drives the equity benefit accounting described in §3.6 and §3.7.

Amending a member is likewise reserved to a `RegionalAdministrator`, who may supply any combination of `status`, `endorsement_weight` and `svi_score`. Supplying a new `svi_score` recomputes `svi_tier` and `disadvantaged_flag` on the spot. Supplying a new `endorsement_weight` changes the denominator of every *future* endorsement tally but never retroactively changes the weight frozen on an endorsement that has already been cast — the mechanics of that freeze are in §3.8. Every amendment increments the member's `version` by 1.

Membership standing gates participation. Any write that names a jurisdiction — proposing a project, casting an endorsement, scheduling an engagement session, creating a mutual aid pact, or creating a mutual aid commitment — requires that the named `Jurisdiction` be in `ACTIVE` standing. A member in `PROBATION` or `SUSPENDED` standing cannot do any of those five things, and the attempt is rejected with `ERR_JURISDICTION_NOT_ACTIVE`. This check sits above every plan-cycle state check, so a suspended member trying to endorse a cycle that is not even open for endorsement sees `ERR_JURISDICTION_NOT_ACTIVE` first. A suspended member also leaves the endorsement denominator entirely, as §3.8 explains.

### 3.2. Downscaled Hazard Projections and the Republication Cascade

A `HazardAnalyst` records a downscaled climate projection for one member government and one hazard. The payload names the covered `jurisdiction_id`, the `hazard_type` — one of `HEAT`, `FLOOD`, `DROUGHT` or `STORM` — the emissions `scenario`, either `RCP45` or `RCP85`, the projection `horizon_year`, which must be exactly 2040, 2060 or 2080, and three quantitative results: `exposure_index`, a normalized exposure magnitude with 2 fractional digits between 0.00 and 1.00 inclusive; `annual_event_probability`, the annual exceedance probability of the design event, carried to 4 fractional digits and constrained to at least 0.0001 and at most 1.0000; and `projected_annual_loss_cents`, the downscaled expected annual loss for that jurisdiction under that hazard, in whole cents and never negative. A newly recorded projection begins in `status` `DRAFT` with `published_version` 0 and `published_at` null.

Publication is a separate, deliberate act by a `HazardAnalyst`, and it moves the profile `DRAFT → PUBLISHED`. Publishing a profile that is not in `DRAFT` is rejected with `ERR_HAZARD_PROFILE_ALREADY_PUBLISHED`. On success the server sets `published_version` to 1 and stamps `published_at` with the logical clock instant. Publication also supersedes: if another profile already sits in `PUBLISHED` for the very same combination of `jurisdiction_id`, `hazard_type`, `scenario` and `horizon_year`, that older profile's `status` moves to `SUPERSEDED`. Both rows have their `version` incremented. Only a `PUBLISHED` profile may back a vulnerability assessment; `SUPERSEDED` is terminal.

**Republication is where the system earns its keep.** When the science team re-runs a downscaled model, the analyst posts a revision against the already-published profile, supplying fresh values for `exposure_index`, `annual_event_probability` and `projected_annual_loss_cents`. The profile stays in `PUBLISHED` — this is a self-loop, `PUBLISHED → PUBLISHED`, at a higher publication counter. Revising a profile that is not currently `PUBLISHED` is rejected with `ERR_HAZARD_PROFILE_NOT_PUBLISHED`. What follows is a five-hop transitive cascade, and each hop is caused by the mutation the previous hop made:

- **Hop 1.** The three projection fields are overwritten from the request, `published_version` increments by 1, and `published_at` is refreshed to the current logical clock instant.
- **Hop 2.** *Because* `published_version` advanced, every vulnerability assessment against this profile that sits in `ASSESSED` and whose `assessed_profile_version` is now strictly less than the profile's `published_version` moves `ASSESSED → STALE`. It does not pass through `DRAFT`. Its `vulnerability_score` and `vulnerability_band` are **retained** as the stale reading, so a reader can still see what the old number was.
- **Hop 3.** *Because* those assessments went stale, every lifeline asset that is the `asset_id` of one of them and currently sits in `criticality_status` `RANKED` moves `RANKED → RECOMPUTE_REQUIRED`, and its `consequence_score`, `criticality_tier` and `dependency_depth` are all set to null. Unlike hop 2, the ranking outputs are discarded rather than retained.
- **Hop 4.** *Because* those assets now require recomputation, every benefit-cost analysis in `CERTIFIED` status whose project is linked to one of those assets moves `CERTIFIED → STALE` with `stale_reason` set to `ASSET_RECOMPUTE`, and the owning adaptation project's `analysis_status` moves `BCA_CERTIFIED → BCA_STALE`.
- **Hop 5.** *Because* those projects' analyses went stale, every plan cycle that owns one of them and currently sits in `ENDORSEMENT_ROUND` is pushed back: it moves `ENDORSEMENT_ROUND → REVISION` with `revision_count` incremented by 1 and every live current-round endorsement marked `SUPERSEDED`, provided `revision_count` plus 1 is still within `max_revision_rounds`. If `revision_count` plus 1 would exceed `max_revision_rounds`, the cascade writes `ENDORSEMENT_ROUND → FAILED` instead, carrying the same endorsement supersession and the same cancellation side effects as the operator-driven failure described in §3.8.

Every row touched by any of the five hops has its `version` incremented by 1 and its `updated_at` refreshed. A team that republishes a projection at the wrong moment can therefore lose an entire endorsement round — which is precisely the coordination signal the agency wants surfaced rather than hidden.

### 3.3. Vulnerability Assessment Across Infrastructure, Populations and Economic Sectors

A vulnerability assessment pairs one published hazard projection with one lifeline asset and asks how badly a particular class of receptor in that asset's service area would suffer. A `HazardAnalyst` opens one by supplying the `hazard_profile_id` of the downscaled projection that will supply the exposure term, the `asset_id` of the asset whose service area the receptor sits in, the `subject_type` naming the receptor dimension — `INFRASTRUCTURE`, `POPULATION` or `ECONOMIC_SECTOR` — a `sensitivity_score` and an `adaptive_capacity_score`, each a decimal with 2 fractional digits between 0.00 and 1.00 inclusive, and the `method` that selects which algorithm variant will be applied. The payload may also carry `svi_overlay_applied`, which defaults to true when omitted. A newly opened assessment sits in `status` `DRAFT` with `vulnerability_score`, `vulnerability_band`, `assessed_at` and `assessed_profile_version` all null.

Assessing the row is a distinct act by a `HazardAnalyst` that takes no payload of its own — everything it needs is already on the row and on the projection it points at. Two conditions guard it, and they are evaluated in this order: **first** the referenced hazard profile must currently be in `PUBLISHED` status, and a profile still in `DRAFT` or already `SUPERSEDED` yields `ERR_HAZARD_PROFILE_NOT_PUBLISHED`; **then** the assessment itself must be in either `DRAFT` or `STALE`, and an assessment already sitting in `ASSESSED` yields `ERR_ASSESSMENT_NOT_PENDING`. Because the publication check runs first, an analyst re-assessing an already-assessed row against a superseded profile is told about the profile, not about the row. On success the row moves `DRAFT → ASSESSED` on its first pass, or `STALE → ASSESSED` when it is being refreshed after a republication; either way `assessed_at` is stamped with the logical clock instant, `assessed_profile_version` is set to the profile's current `published_version`, and the assessment's `version` increments by 1. Recording `assessed_profile_version` is what makes hop 2 of §3.2's cascade decidable: an assessment whose recorded counter has fallen behind the profile's counter is by definition stale.

The score itself is assembled from five ingredients. The **exposure term** is the `exposure_index` currently carried by the referenced hazard profile — which is why re-assessing a stale row after a republication produces a different number from a value computed against the older run. The **sensitivity term** is the row's `sensitivity_score`. The **adaptive gap** is one minus the row's `adaptive_capacity_score`, so a receptor with high adaptive capacity contributes less. The **social vulnerability multiplier** is looked up from the `svi_tier` of the jurisdiction that owns the linked lifeline asset, and takes the value 1.00 for `LOW`, 1.10 for `MODERATE`, 1.25 for `HIGH` and 1.40 for `SEVERE`; when the row's `svi_overlay_applied` is false, the multiplier is 1.00 regardless of the tier. The **subject uplift** is a flat additive term keyed on `subject_type`: 0.00 for `INFRASTRUCTURE`, 0.05 for `POPULATION` and 0.03 for `ECONOMIC_SECTOR`.

The two variants combine the first three ingredients differently, and they are not monotone transforms of one another — the multiplicative form collapses toward zero as soon as any single factor is small, while the additive form keeps a floor contribution from every dimension, so identical inputs routinely land in different bands. Under `COMPOSITE_MULTIPLICATIVE`, the raw figure is the exposure term multiplied by the sensitivity term multiplied by the adaptive gap. Under `ADDITIVE_WEIGHTED`, the raw figure is the exposure term weighted at 0.40, plus the sensitivity term weighted at 0.35, plus the adaptive gap weighted at 0.25.

The raw figure is then multiplied by the social vulnerability multiplier, and the subject uplift is added to that product. The result is clamped to lie between a floor of 0.00 and a ceiling of 1.00 — **the clamp is applied to the unrounded value** — and the clamped value is then rounded half up to 2 fractional digits to give `vulnerability_score`. Finally `vulnerability_band` is read off the **rounded** score, never the unrounded one: `EXTREME` when the score is at least 0.75, `HIGH` when it is at least 0.50, `MODERATE` when it is at least 0.25, and `LOW` otherwise.

### 3.4. The Lifeline Dependency Graph and Asset Criticality Ranking

The lifeline register is maintained by a `RegionalAdministrator`. Adding an asset means naming its owning `jurisdiction_id`, the `asset_class` it belongs to — `WATER`, `POWER`, `TRANSPORT`, `HEALTH` or `COMMS` — a display `name` of 1 to 120 non-blank characters, its full `replacement_value_cents` in whole cents which must be at least 1, the `service_population` who lose service if it fails which must be zero or more, and its `redundancy_factor`, a decimal with 2 fractional digits between 0.00 and 1.00 inclusive expressing the share of the asset's function already covered by redundant capacity. Two optional fields complete the picture: `is_shared`, which defaults to false and marks an asset that serves more than one member jurisdiction, and `upstream_asset_id`, which defaults to null and names the asset this one depends on for continued service. A new asset always begins in `criticality_status` `UNRANKED` with `consequence_score`, `criticality_tier` and `dependency_depth` all null.

Those `upstream_asset_id` pointers form the **lifeline dependency graph**: a water pumping station depends on a substation, which depends on a transmission tie. An asset with a null `upstream_asset_id` is a root. The graph must remain acyclic. Whenever an asset is created, whenever its dependency edge is rewritten, and again whenever it is ranked, the server walks the chain of `upstream_asset_id` pointers upward and must reach a null without revisiting any identifier; pointing an asset's upstream edge at one of its own downstream assets closes a loop and is rejected with `ERR_ASSET_DEPENDENCY_CYCLE`. A `RegionalAdministrator` may amend an existing asset's `is_shared` flag and its `upstream_asset_id`, but only while the asset sits in `UNRANKED` or `RECOMPUTE_REQUIRED` — amending an asset that is currently `RANKED` is rejected with `ERR_ASSET_ALREADY_RANKED`, because rewriting a dependency edge under a live ranking would invalidate it. A successful amendment increments the asset's `version` by 1.

Ranking is a `HazardAnalyst` act that moves `UNRANKED → RANKED` on a first pass and `RECOMPUTE_REQUIRED → RANKED` when an asset is being re-ranked after a republication cascade. Three conditions guard it, evaluated in this order: **first** the asset must be in `UNRANKED` or `RECOMPUTE_REQUIRED`, and an asset already `RANKED` yields `ERR_ASSET_ALREADY_RANKED`; **then** the upstream chain must be acyclic, yielding `ERR_ASSET_DEPENDENCY_CYCLE` if it is not; **then** the asset must have at least one vulnerability assessment in `ASSESSED` status, yielding `ERR_NO_ASSESSED_VULNERABILITY` if it does not. That last check is stricter than it looks: rows sitting in `DRAFT` or `STALE` are excluded from the input set entirely, so an asset whose only assessments have gone stale after a republication cannot be ranked until at least one of them is re-assessed, and the rejection leaves no partial write behind.

The ranking writes three fields. **`dependency_depth`** is the number of hops from this asset up its chain of `upstream_asset_id` pointers to the root; a root asset has a depth of 0, an asset one hop below a root has a depth of 1, and so on. **`consequence_score`** is a failure-consequence figure assembled as follows. The asset's exposed value is its `replacement_value_cents` multiplied by one minus its `redundancy_factor`, rounded half up to whole cents; that whole-cent figure is then divided by one hundred million cents — that is, expressed in units of one million dollars — to give the value term. The **peak vulnerability** term is the largest `vulnerability_score` found across the asset's `ASSESSED` assessments. The **cascade factor** is 1.00 plus 0.15 for each hop of dependency depth, counting at most three hops, so a depth of 0 gives 1.00, a depth of 1 gives 1.15, a depth of 2 gives 1.30, and a depth of 3 or anything deeper gives 1.45 and no more. The **sharing factor** is 1.20 when the asset's `is_shared` is true and 1.00 otherwise. The **population weight** is the asset's `service_population` capped at 250,000 residents and then divided by 250,000, so it runs from 0 to 1 inclusive. `consequence_score` is then the value term multiplied by the peak vulnerability term, multiplied by the cascade factor, multiplied by the sharing factor, multiplied by one plus the population weight — rounded half up, once, at the very end, to 2 fractional digits. **`criticality_tier`** is read off that rounded score: `TIER_1` when it is at least 25.00, `TIER_2` when it is at least 8.00, and `TIER_3` otherwise. The asset's `version` increments by 1.

### 3.5. Proposing Adaptation Strategies and Screening Them

A `ProjectSponsor` proposes an adaptation project into a plan update cycle. The payload names the `plan_cycle_id` of the cycle the project belongs to, the sponsoring `jurisdiction_id` — which must equal the sponsor's own `X-User-ID`, per §2.5 — a display `name` of 1 to 120 non-blank characters, the primary `hazard_type` the project addresses drawn from `HEAT`, `FLOOD`, `DROUGHT` and `STORM`, the `strategy_type` naming the adaptation family, the planning-level `base_cost_cents` in whole cents which must be at least 1, the design `service_life_years` which must lie between 10 and 75 inclusive, the `cobenefit_points` awarded during strategy screening which must lie between 0 and 20 inclusive, and a `feasibility_score` with 2 fractional digits between 0.00 and 1.00 inclusive. Three optional fields may accompany them: `prerequisite_project_id`, naming a project that must be awarded before this one may progress; and the implementation-tracking pair `indicator_code`, a string of 1 to 40 characters, and `indicator_target_value`, a decimal with 2 fractional digits that must be strictly greater than zero. All three default to null. `strategy_type` is one of `PROTECT`, `ACCOMMODATE`, `RETREAT` or `AVOID`.

Proposal is gated three ways. The sponsoring jurisdiction must be `ACTIVE`. The named plan cycle must be in `DRAFT`, `ENGAGEMENT` or `REVISION` — a cycle already in `ENDORSEMENT_ROUND`, `ADOPTED` or `FAILED` accepts no new projects and yields `ERR_PLAN_CYCLE_STATE_INVALID`. And the chain of `prerequisite_project_id` pointers walked upward from the new project must reach a null without revisiting any identifier; pointing a prerequisite at a project that already depends on the new one is rejected with `ERR_PROJECT_PREREQUISITE_CYCLE`.

A project is the only entity in the system that carries **four independent state dimensions on one row**, and they are never collapsed into a single status field. `screening_status` tracks strategy screening, `analysis_status` tracks benefit-cost review, `program_status` tracks capital programming and grants, and `implementation_status` tracks delivery against indicators. They advance on different triggers, driven by different roles, and a single project can legitimately read `SCREENED_IN`, `BCA_STALE`, `AWARDED` and `AT_RISK` all at once. A freshly proposed project reads `screening_status` `PROPOSED`, `analysis_status` `NOT_ANALYZED`, `program_status` `UNPROGRAMMED` and `implementation_status` `NOT_STARTED`. Alongside those, `grant_hold_flag` and `equity_waiver_granted` are both false, `allocated_cents` and `reported_period_count` are both 0, and `capital_program_id`, `escalated_cost_cents`, `admin_rate_bps`, `admin_fee_cents`, `total_program_cost_cents`, `grant_match_share_bps`, `screen_score`, `priority_score`, `equity_benefit_share_bps`, `grant_funder`, `grant_submitted_at`, `awarded_at`, `indicator_latest_value`, `indicator_attainment_pct` and `latest_period_label` are all null until the action that produces each of them runs.

A sponsor may later amend a project's `prerequisite_project_id`, `indicator_code` and `indicator_target_value`, and only those three. Rewriting the prerequisite edge re-walks the chain for a repeated identifier and can therefore raise `ERR_PROJECT_PREREQUISITE_CYCLE` just as creation can. Amendment is permitted only while `program_status` is still `UNPROGRAMMED`; once capital has been committed, a project's prerequisite and indicator definition are frozen, and the attempt is rejected with `ERR_PROJECT_ALREADY_PROGRAMMED`. A successful amendment increments the project's `version` by 1.

**Screening** is a `RegionalAdministrator` act, and it is where the project first acquires a price. Screening a project whose `screening_status` is anything other than `PROPOSED` is rejected with `ERR_PROJECT_ALREADY_SCREENED`. Screening runs the cost stack in a **pinned five-step order that is normative**:

- **Step 1 — escalation.** `escalated_cost_cents` is `base_cost_cents` inflated by the escalation rate of the project's `strategy_type`, rounded half up to whole cents. A `PROTECT` project escalates by 1200 basis points, `ACCOMMODATE` by 800, `RETREAT` by 1500 and `AVOID` by 500 — that is, twelve, eight, fifteen and five percent respectively.
- **Step 2 — administration rate.** `admin_rate_bps` is selected from a three-band schedule keyed on the **Step 1 result**, not on the eventual total. An escalated cost from zero up to but not including five hundred thousand dollars attracts 900 basis points; from five hundred thousand dollars up to but not including five million dollars attracts 600 basis points; and five million dollars or more attracts 350 basis points. Each band's lower bound is inclusive and its upper bound exclusive.
- **Step 3 — administration fee.** `admin_fee_cents` is the escalated cost multiplied by `admin_rate_bps` expressed as a fraction of ten thousand, rounded half up to whole cents.
- **Step 4 — total.** `total_program_cost_cents` is the exact integer sum of the already-rounded `escalated_cost_cents` and the already-rounded `admin_fee_cents`. No further rounding occurs here.
- **Step 5 — local match share.** `grant_match_share_bps` is selected from a second three-band schedule keyed on `total_program_cost_cents`. A total from zero up to but not including one million dollars requires a 2500 basis-point local match; from one million dollars up to but not including ten million dollars requires 3000; and ten million dollars or more requires 3500. Again lower bounds are inclusive and upper bounds exclusive.

**Step 2 is never re-evaluated after Step 4.** Adding the administration fee can push the running amount across the five-hundred-thousand-dollar band boundary, but the administration rate stays the one that Step 1's result selected. Keying the administration rate on the total instead of on the escalated cost is the single most common way to get this calculation wrong, and it produces a *lower* fee and a *lower* total than the correct answer.

With the cost stack in hand, screening computes `screen_score`. The **cost component** is one minus the project's `total_program_cost_cents` divided by a two-million-dollar normalizer, with that ratio capped at 1.00 before the subtraction — so a project whose total program cost reaches or exceeds two million dollars has a cost component of exactly 0 and never a negative one. The **co-benefit component** is `cobenefit_points` divided by the maximum of 20 points. The **feasibility component** is the project's `feasibility_score` as supplied. `screen_score` is then the cost component weighted at 0.40, plus the co-benefit component weighted at 0.25, plus the feasibility component weighted at 0.35 — with the cost component carried into that weighted sum **unrounded**, and the sum rounded half up, once, to 4 fractional digits.

The screening outcome is decided on the **rounded** `screen_score` against a floor of 0.4500. A score of at least 0.4500 moves the project `PROPOSED → SCREENED_IN`; a score below 0.4500 moves it `PROPOSED → SCREENED_OUT`, which is terminal for the screening dimension. Both outcomes write exactly the same fields: `escalated_cost_cents`, `admin_rate_bps`, `admin_fee_cents`, `total_program_cost_cents`, `grant_match_share_bps` and `screen_score` are all persisted on either branch, and the project's `version` increments by 1 either way. A screened-out project is priced and scored for the record even though it will go no further.

### 3.6. Attributing Benefits to Assets, and Certifying the Benefit-Cost Case

Before a project can be analysed it must say which lifeline assets it actually protects. A `ProjectSponsor` attributes benefit by linking the project to an asset, supplying the `asset_id` of the protected lifeline asset and the `avoided_loss_annual_cents` — the annual loss avoided at that asset once the project is in service, in whole cents and never negative. The payload may also carry `benefit_reaches_disadvantaged`; when it is omitted, the server fills it from the `disadvantaged_flag` of the jurisdiction that owns the linked asset. That value is a **snapshot taken at link creation** and is not re-read later, so a jurisdiction whose social vulnerability tier is subsequently revised does not retroactively change the equity attribution of links already written.

Linking is permitted only while the project's `screening_status` is `SCREENED_IN`; a project still in `PROPOSED`, or one that was `SCREENED_OUT`, is rejected with `ERR_PROJECT_NOT_SCREENED_IN`. That check runs before the uniqueness check: a project may not link the same asset twice, and posting a `project_id` and `asset_id` pair that already exists is rejected with `ERR_DUPLICATE_ASSET_LINK`. Each accepted link is stamped with a `link_sequence` equal to one plus the count of links already held by that project, ordered by `created_at` ascending — so the first link on a project is 1, the second is 2, and so on. That sequence is not cosmetic: it pins the per-line rounding order of the discounted benefit-cost calculation below, and it is the reason a link row is immutable.

Adding a link has one further consequence. If the project already holds a `CERTIFIED` benefit-cost analysis, that analysis's benefit input set has just changed, so it moves `CERTIFIED → STALE` with `stale_reason` set to `LINK_ADDED`, and the project's `analysis_status` moves `BCA_CERTIFIED → BCA_STALE`. `stale_reason` therefore distinguishes the two ways a certified case can be invalidated: `ASSET_RECOMPUTE` when a linked asset lost its ranking through the republication cascade of §3.2, and `LINK_ADDED` when a fresh link changed the benefit set. It reads `NONE` on any analysis that has not gone stale.

**Preparing an analysis** is also a `ProjectSponsor` act. The payload names the `method` — either `DISCOUNTED_NPV` or `ANNUALIZED_EQUIVALENT` — and may carry `discount_rate_bps`, the real discount rate in basis points, which defaults to 700 when omitted and whose declared domain is at least 1 and at most 2000. Four conditions guard preparation, evaluated in this order: the project's `screening_status` must be `SCREENED_IN`, or `ERR_PROJECT_NOT_SCREENED_IN`; no analysis for the project may currently sit in `CERTIFIED`, or `ERR_BCA_ALREADY_CERTIFIED`; the project must have at least one linked asset, or `ERR_NO_LINKED_ASSETS`; and every lifeline asset reachable through the project's links must sit in `criticality_status` `RANKED`, or `ERR_ASSET_RANKING_REQUIRED`. That last rule is what forces a sponsor to wait for the science team to re-rank an asset after a republication before a new case can be built on it.

A newly prepared analysis is created in `status` `DRAFT` with `stale_reason` `NONE`, records the acting user's identifier as `prepared_by_user_id`, and copies the project's `service_life_years` onto the analysis as `analysis_horizon_years` — a snapshot observed at creation, so the horizon used by the case is fixed even if the project's design life is later restated. Preparation moves the project's `analysis_status` to `BCA_PENDING`, and that move may be entered from three different origins: `NOT_ANALYZED → BCA_PENDING` on a first attempt, `BCA_REJECTED → BCA_PENDING` after a reviewer turned an earlier case down, or `BCA_STALE → BCA_PENDING` after a cascade invalidated a certified one. Re-preparation after a rejection does **not** require re-screening the project, and the rejected analysis keeps its `REJECTED` status forever — a fresh `DRAFT` row is created alongside it. Re-preparation after staleness additionally re-checks that every linked asset is `RANKED`, so the new case is computed against the re-ranked assets.

The calculation itself walks the project's links in `link_sequence` ascending order and produces four fields: `benefit_measure_cents`, `cost_measure_cents`, `bcr` and `grant_eligible`. Three inputs are common to both variants: the discount rate expressed as a fraction, which is `discount_rate_bps` divided by ten thousand; the horizon in years, which is the project's `service_life_years`; and the capital amount, which is the project's `total_program_cost_cents`. An operations-and-maintenance burden of two percent of the capital amount per year applies to the cost side under both variants.

Under **`DISCOUNTED_NPV`**, the server first computes an **annuity factor**: one, minus the quantity one plus the discount rate raised to the power of the negative horizon, all divided by the discount rate. That factor is carried at full decimal precision and is never rounded. Then, **for each link in `link_sequence` ascending order**, the link's `avoided_loss_annual_cents` is multiplied by the annuity factor and that product is rounded half up to whole cents; `benefit_measure_cents` is the sum of those already-rounded per-link amounts. The rounding order here is normative: **round each link first, then sum.** Summing the raw products and rounding once at the end can differ by a cent and is wrong. On the cost side, `cost_measure_cents` is the capital amount plus the discounted operations-and-maintenance stream, where that stream is the capital amount multiplied by two percent multiplied by the annuity factor, rounded half up to whole cents.

Under **`ANNUALIZED_EQUIVALENT`**, no discounting happens at all. `benefit_measure_cents` is the exact integer sum of every link's `avoided_loss_annual_cents` — one undiscounted year of benefit. `cost_measure_cents` is the capital amount divided by the horizon in years and rounded half up to whole cents, plus the capital amount multiplied by two percent and rounded half up to whole cents — one straight-line year of capital plus one year of operations and maintenance. The two amounts are rounded independently and then added exactly.

The two variants are emphatically not reciprocals of one another and routinely land on opposite sides of the eligibility floor: the discounted form loads a whole horizon of discounted upkeep onto the cost while discounting the benefit stream, whereas the annualized form compares a single year against a single year. In both cases `bcr` is `benefit_measure_cents` divided by `cost_measure_cents`, rounded half up to exactly 4 fractional digits, and `grant_eligible` is true exactly when that **rounded** `bcr` is at least 1.0000. A case that computes to 0.99995 before rounding is therefore eligible, because it rounds to 1.0000.

**Certification** belongs to a `BCAReviewer` and is the point at which the case becomes usable for funding. Four conditions guard it, in this order: the analysis must be in `DRAFT`, and one already `CERTIFIED`, `REJECTED` or `STALE` yields `ERR_ANALYSIS_NOT_DRAFT`; no other analysis for the same project may already be `CERTIFIED`, yielding `ERR_BCA_ALREADY_CERTIFIED`; the reviewer's `X-User-ID` must differ from the analysis's `prepared_by_user_id`, yielding `ERR_SEGREGATION_OF_DUTIES`; and the `bcr` must be at least 1.0000, yielding `ERR_BCR_BELOW_FLOOR`. On success the analysis moves `DRAFT → CERTIFIED`, `certified_by_user_id` records the reviewer, `certified_at` is stamped from the logical clock, `stale_reason` is set to `NONE`, the owning project's `analysis_status` moves `BCA_PENDING → BCA_CERTIFIED`, and the analysis's `version` increments by 1.

Rejection is the same reviewer's other option, and it carries only two of those four guards: the analysis must be in `DRAFT`, or `ERR_ANALYSIS_NOT_DRAFT`, and the reviewer must not be the preparer, or `ERR_SEGREGATION_OF_DUTIES`. A reviewer may reject a case whose ratio is perfectly healthy. On success the analysis moves `DRAFT → REJECTED`, which is terminal for that row, the owning project's `analysis_status` moves `BCA_PENDING → BCA_REJECTED`, and the analysis's `version` increments by 1.

### 3.7. Capital Programming, the Equity Gate, Grants and Implementation Tracking

A `RegionalAdministrator` opens a regional capital program for a `fiscal_year` between 2026 and 2040 inclusive, with an `authorized_cents` programming capacity of at least 1 cent, and optionally an `equity_target_bps` that defaults to 4000 basis points and must lie between 0 and 10000 inclusive. A new program starts with `committed_cents` 0, `available_cents` equal to `authorized_cents`, `equity_committed_cents` 0, `equity_achieved_bps` 0 and `funding_posture` `OPEN`.

**Allocating** capital is the act that moves a project's `program_status` `UNPROGRAMMED → PROGRAMMED`. The request names the `project_id` to be funded, the `allocated_cents` to commit, and the `expected_capital_program_version` described in §2.7. Seven conditions guard it, and they are evaluated in exactly this order:

1. The project's `program_status` must be `UNPROGRAMMED`; allocating twice to the same project yields `ERR_PROJECT_ALREADY_PROGRAMMED`.
2. `expected_capital_program_version` must equal the program's current `version`, or `ERR_STALE_PROGRAM_VERSION` (HTTP 412), evaluated before any ledger field is read for writing.
3. The project's `equity_benefit_share_bps` must be at least the program's `equity_target_bps`, **or** the project's `equity_waiver_granted` must be true; otherwise `ERR_EQUITY_FLOOR_NOT_MET`.
4. Every lifeline asset reachable through the project's links must sit in `criticality_status` `RANKED`, or `ERR_ASSET_RANKING_REQUIRED`.
5. The project's `analysis_status` must be `BCA_CERTIFIED`, or `ERR_BCA_NOT_CERTIFIED` — a project whose analysis reads `BCA_PENDING`, `BCA_REJECTED` or `BCA_STALE` cannot be funded.
6. `allocated_cents` may not exceed the project's `total_program_cost_cents`, or `ERR_ALLOCATION_EXCEEDS_PROJECT_COST` (HTTP 422).
7. `allocated_cents` may not exceed the program's current `available_cents`, or `ERR_PROGRAM_FUNDS_EXCEEDED`.

The equity share the third check reads is derived from the project's own links: `equity_benefit_share_bps` is ten thousand times the sum of `avoided_loss_annual_cents` over the links whose `benefit_reaches_disadvantaged` is true, divided by the sum of `avoided_loss_annual_cents` over **all** the project's links, **floored** to a whole number of basis points. Flooring, never rounding, is normative here — a share that works out to 61.53 percent is 6153 basis points.

A successful allocation writes `capital_program_id` and `allocated_cents` onto the project, and computes its `priority_score` from three weighted components. The **ratio component** is the certified analysis's `bcr` capped at 3.0000 and then divided by 3.0000, so any ratio at or above 3.0000 contributes the full amount. The **criticality component** is the largest tier value among the assets the project links to, where `TIER_1` is worth 1.00, `TIER_2` is worth 0.60 and `TIER_3` is worth 0.30 — the single most critical asset the project protects sets this term. The **equity component** is `equity_benefit_share_bps` divided by ten thousand, capped at 1.0000. `priority_score` is the ratio component weighted at 0.45, plus the criticality component weighted at 0.30, plus the equity component weighted at 0.25; the ratio and equity components are carried into that sum unrounded, and only the final sum is rounded half up to 4 fractional digits.

The allocation then **recomputes the program ledger from scratch** rather than adjusting it by a delta. The input set is every adaptation project whose `capital_program_id` is this program and whose `program_status` is `PROGRAMMED`, `GRANT_SUBMITTED` or `AWARDED`; projects in `UNPROGRAMMED` and `WITHDRAWN` are excluded, and this matters because a withdrawn project **keeps** its `capital_program_id` for audit purposes while contributing nothing to the ledger. Over that set, `committed_cents` is the sum of `allocated_cents`, and `available_cents` is `authorized_cents` minus `committed_cents`. `equity_committed_cents` is the sum of `allocated_cents` restricted to those projects whose `equity_benefit_share_bps` is at least the program's `equity_target_bps`. `equity_achieved_bps` is 0 when `committed_cents` is 0, and otherwise ten thousand times `equity_committed_cents` divided by `committed_cents`, floored.

`funding_posture` is then re-derived in this order: `CLOSED` when `available_cents` is exactly zero; otherwise `OVERSUBSCRIBED` when `available_cents` is greater than zero and the remaining headroom — ten thousand times `available_cents` divided by `authorized_cents`, floored to whole basis points — is strictly below 1000 basis points, that is, strictly below ten percent of authorized capacity; and `OPEN` otherwise. The boundary is exact and inclusive on the healthy side: a program with headroom of exactly 1000 basis points is **not** oversubscribed and reads `OPEN`, while one cent less of headroom drops it to 999 basis points and reads `OVERSUBSCRIBED`.

Whenever the recomputed posture is `CLOSED`, the system sets `grant_hold_flag` to true on **every** project of that program whose `program_status` is `PROGRAMMED` — not merely on the project just funded. The program's `version` increments by 1, and the allocated project's `version` increments by 1.

The **equity waiver** is the escape valve on the third check, and it belongs exclusively to the `EquityOfficer`. The request carries a `waiver_rationale` recording why the exception is justified, sets `equity_waiver_granted` to true on the project, and increments the project's `version` by 1. A waived project clears the equity gate no matter how low its equity benefit share is.

**Grant submission** is a `ProjectSponsor` act carrying the `grant_funder` the application targets: `BRIC`, `HMGP` or `STATE_RESILIENCE`. Four conditions guard it, in this order: the project's `program_status` must be `PROGRAMMED`, or `ERR_PROJECT_NOT_PROGRAMMED`; the project's `prerequisite_project_id` must be null or the prerequisite project's own `program_status` must already be `AWARDED`, or `ERR_PREREQUISITE_NOT_AWARDED`; the project's certified analysis must be grant-eligible, meaning its `bcr` is at least 1.0000 and its `grant_eligible` is true, or `ERR_BCR_BELOW_FLOOR`; and the project's `grant_hold_flag` must be false, or `ERR_GRANT_ON_HOLD`. On success the project moves `PROGRAMMED → GRANT_SUBMITTED`, `grant_funder` and `grant_submitted_at` are written from the request and the logical clock respectively, and the project's `version` increments by 1.

**Awarding** the grant is reserved to a `RegionalAdministrator`, and it requires the project's `program_status` to be `GRANT_SUBMITTED` — anything else yields `ERR_PROJECT_NOT_PROGRAMMED` — and its `analysis_status` to still be `BCA_CERTIFIED`, or `ERR_BCA_NOT_CERTIFIED`. The two checks run in that order. On success the project moves `GRANT_SUBMITTED → AWARDED`, `awarded_at` is stamped from the logical clock, `implementation_status` remains `NOT_STARTED` until the first indicator report arrives, and the project's `version` increments by 1. `AWARDED` is terminal for the programming dimension.

**Withdrawal** is the compensating operation, available to a `ProjectSponsor` while the project's `program_status` is either `PROGRAMMED` or `GRANT_SUBMITTED`; any other state yields `ERR_PROJECT_NOT_PROGRAMMED`. It runs a four-hop cascade that exactly reverses the allocation with no ledger drift:

- **Hop 1.** The project's `program_status` moves to `WITHDRAWN` and its `allocated_cents` is reset to 0. `capital_program_id` is deliberately **retained** for audit. On the `GRANT_SUBMITTED → WITHDRAWN` branch, `grant_funder` and `grant_submitted_at` are likewise retained; the hops are otherwise identical to the `PROGRAMMED → WITHDRAWN` branch.
- **Hop 2.** *Because* the project has left the committed set, the program's `committed_cents` decreases by exactly the released amount and `available_cents` increases by exactly the same amount, so `committed_cents` plus `available_cents` still equals `authorized_cents`. `equity_committed_cents` and `equity_achieved_bps` are recomputed over the surviving set.
- **Hop 3.** *Because* `available_cents` has risen above zero, `funding_posture` is re-derived by the same ordered rule as above and therefore leaves `CLOSED`.
- **Hop 4.** *Because* the posture has left `CLOSED`, `grant_hold_flag` is cleared to false on **every sibling project** of that program whose `program_status` is `PROGRAMMED`.

The program's `version` increments by 1, and so does the `version` of every project row the cascade touches. `WITHDRAWN` is terminal for the programming dimension.

**Implementation tracking** begins once the grant is awarded. A `ProjectSponsor` files a periodic report carrying the `reported_value` observed and the `period_label` naming the reporting period. Two conditions guard it, in this order: the project's `program_status` must be `AWARDED`, or `ERR_PROJECT_NOT_PROGRAMMED`; and both `indicator_code` and `indicator_target_value` must be non-null on the project, or `ERR_INDICATOR_NOT_DEFINED` — a project created without an indicator definition must have one added by amendment before any report can be filed, and amendment is only possible while the project is still `UNPROGRAMMED`, so in practice the indicator must be defined early.

Each report writes `indicator_latest_value` from `reported_value`, `latest_period_label` from `period_label`, and `indicator_attainment_pct` as one hundred multiplied by `reported_value` divided by `indicator_target_value`, rounded half up to 2 fractional digits. `reported_period_count` increments by 1 with every report, and the project's `version` increments by 1. `implementation_status` is then re-derived from the **rounded** attainment percentage: `ON_TRACK` when it is at least 90.00, `AT_RISK` when it is at least 70.00, and `OFF_TRACK` otherwise. Both floors are inclusive, so an attainment of exactly 90.00 reads `ON_TRACK` and exactly 70.00 reads `AT_RISK`, while 89.99 reads `AT_RISK` and 69.90 reads `OFF_TRACK`. Each report **overwrites** `indicator_attainment_pct` with the newest period's figure rather than averaging, and the status is fully re-derivable **in both directions**: a project may slide `NOT_STARTED → ON_TRACK`, `NOT_STARTED → AT_RISK` or `NOT_STARTED → OFF_TRACK` on its first report, deteriorate `ON_TRACK → AT_RISK` on a weak period, and recover `OFF_TRACK → ON_TRACK` on a strong one.

### 3.8. Community Engagement and the Weighted Endorsement Loop

The regional plan is updated on a cycle, and the cycle is the only entity in the system whose lifecycle is genuinely **cyclic**. A `RegionalAdministrator` opens one by supplying a `cycle_label` of 1 to 80 non-blank characters and an `endorsement_deadline`, the ISO 8601 UTC instant after which no endorsement may be cast for that cycle. Three governance parameters may also be supplied: `quorum_weight_bps`, the supporting-weight share required to adopt, which defaults to 6600 basis points — two-thirds rounded up to the nearest hundredth of a percent, or sixty-six percent — and must lie between 1 and 10000 inclusive; `max_revision_rounds`, the revision budget, which defaults to 2 and must lie between 0 and 5 inclusive; and `required_session_count`, the number of completed engagement sessions needed before an endorsement round may open, which defaults to 2 and must lie between 0 and 10 inclusive. A new cycle reads `status` `DRAFT`, `round_number` 0, `revision_count` 0, `achieved_weight_bps` null and `adopted_at` null.

Opening engagement is a single administrative step that moves the cycle `DRAFT → ENGAGEMENT`; a cycle in any other state yields `ERR_PLAN_CYCLE_STATE_INVALID`. The cycle's `updated_at` is refreshed and its `version` increments by 1.

**Scheduling an engagement session** belongs to a `JurisdictionDelegate`, who names the `host_jurisdiction_id` that will host it — necessarily their own — the `modality`, one of `IN_PERSON`, `VIRTUAL` or `HYBRID`, and the `window_start` and `window_end` bounding the session. Sessions may be scheduled while the cycle is in `DRAFT`, `ENGAGEMENT` or `REVISION`; any other cycle state yields `ERR_PLAN_CYCLE_STATE_INVALID`. The host jurisdiction must be `ACTIVE`, and `window_start` must be strictly before `window_end` or the request is rejected with `ERR_INVALID_WINDOW`.

A host jurisdiction has **exclusive occupancy** of its session window plus a symmetric travel buffer of 24 hours on each side, because delegates and facilitators cannot be in two places at once. The occupancy set for a candidate booking is every session anywhere in the system with the same `host_jurisdiction_id` whose `status` is `SCHEDULED` or `COMPLETED`; sessions in `CANCELLED` are excluded and never block a new booking. Session windows are treated as **closed** intervals — both endpoints belong to the window — and a candidate conflicts with an existing session when the candidate's `window_start` is at or before the existing session's `window_end` extended forward by 24 hours **and** the existing session's `window_start` is at or before the candidate's `window_end` extended forward by 24 hours. Because both comparisons are inclusive, touching endpoints do conflict, and a booking that starts *exactly* 24 hours after another session ends still conflicts. Any conflict rejects the booking with `ERR_SESSION_WINDOW_CONFLICT`. Occupancy is strictly per host: the identical window hosted by a different member jurisdiction is admitted, and once a conflicting session has been cancelled by a failed cycle the previously blocked candidate becomes admissible. A newly scheduled session reads `status` `SCHEDULED` with `attendee_count`, `disadvantaged_attendee_count`, `equity_reach_bps` and `preferred_strategy_type` all null.

**Completing a session** is the same delegate's follow-up. The payload carries the total `attendee_count`, the `disadvantaged_attendee_count` drawn from disadvantaged communities, and the `preferred_strategy_type` the community selected at the session, which is one of `PROTECT`, `ACCOMMODATE`, `RETREAT` or `AVOID`. Two checks apply, in this order: the session must be in `SCHEDULED`, and one already `COMPLETED` or `CANCELLED` yields `ERR_SESSION_NOT_SCHEDULED`; then `disadvantaged_attendee_count` may not exceed `attendee_count`, or the request is rejected with `ERR_ATTENDANCE_MISMATCH` (HTTP 422). On success the session moves `SCHEDULED → COMPLETED` and `equity_reach_bps` is written as ten thousand multiplied by `disadvantaged_attendee_count` divided by `attendee_count`, **floored** to whole basis points — and defined as 0 when `attendee_count` is 0, so there is never a division by zero. The session's `version` increments by 1.

**Opening an endorsement round** is an administrative act, and it is entered from two different states: `ENGAGEMENT → ENDORSEMENT_ROUND` the first time, and `REVISION → ENDORSEMENT_ROUND` on every subsequent lap of the loop. Both entries carry identical preconditions and identical side effects. Three checks apply, in this order: the cycle must be in `ENGAGEMENT` or `REVISION`, or `ERR_PLAN_CYCLE_STATE_INVALID`; the cycle must have at least `required_session_count` engagement sessions in `COMPLETED` status, or `ERR_ENGAGEMENT_INCOMPLETE` — sessions still `SCHEDULED` and sessions `CANCELLED` never count; and the cycle must own at least one adaptation project whose `screening_status` is `SCREENED_IN`, or `ERR_NO_SCREENED_PROJECTS`. On success `round_number` increments by 1 and the cycle's `version` increments by 1.

**Casting an endorsement** is a `JurisdictionDelegate` act naming the casting `jurisdiction_id` — necessarily their own — and the `decision`. A live decision is `ENDORSED`, `CONDITIONED` or `VETOED`; the fourth enumerated value, `SUPERSEDED`, is never supplied by a client and is written only by the cascade that closes a round without adoption. A `CONDITIONED` decision must be accompanied by a `condition_note` of 1 to 500 characters, and the note must be absent on any other decision. Four checks apply, in this order: the casting jurisdiction must be `ACTIVE`, or `ERR_JURISDICTION_NOT_ACTIVE`; the cycle must be in `ENDORSEMENT_ROUND`, or `ERR_PLAN_CYCLE_STATE_INVALID`; no endorsement may already exist for the same combination of `plan_cycle_id`, `jurisdiction_id` and `round_number` carrying a live decision, or `ERR_DUPLICATE_ENDORSEMENT` — note that an endorsement already marked `SUPERSEDED` does not block a fresh cast, which is exactly what lets a member re-vote in the next round; and `condition_note` must be present and non-empty when the decision is `CONDITIONED`, or `ERR_CONDITION_NOTE_REQUIRED` (HTTP 422). The accepted endorsement is stamped with `round_number` copied from the cycle's current round, `cast_at` from the logical clock, and `weight_at_cast` **frozen** from the casting jurisdiction's `endorsement_weight` at that instant. Freezing the weight is what makes the tally auditable: re-weighting a member after it has voted does not change what that vote already contributes, although it does change the denominator described next.

**Closing the round** is where the fork-join happens: three kinds of endorsement converge into exactly one of three outcomes with three different side-effect sets. The cycle must be in `ENDORSEMENT_ROUND`, or `ERR_PLAN_CYCLE_STATE_INVALID`. The tally is then computed as follows. The **denominator** is the sum of `endorsement_weight` over every jurisdiction whose `status` is `ACTIVE`; members in `PROBATION` or `SUSPENDED` leave the denominator entirely, which means suspending a member mechanically raises everyone else's share. The **numerator set** is every endorsement for this cycle whose `round_number` equals the cycle's current `round_number` and whose `decision` is `ENDORSED`, `CONDITIONED` or `VETOED`; endorsements marked `SUPERSEDED` and endorsements from earlier rounds are excluded. From that set, the **supporting weight** is the sum of `weight_at_cast` over the `ENDORSED` rows, plus half of the sum of `weight_at_cast` over the `CONDITIONED` rows — where the halving is **floored and applied once to the sum of conditioned weights, never per endorsement**. `achieved_weight_bps` is 0 when the denominator is 0, and otherwise ten thousand multiplied by the supporting weight divided by the denominator, floored to whole basis points. The **veto weight** is the sum of `weight_at_cast` over the `VETOED` rows.

The outcome is then decided in this exact order, and step one dominates:

1. If the veto weight is at least 3, the outcome is **blocked** — a veto coalition carrying a combined frozen weight of three or more defeats the plan *even when the supporting weight clears the quorum*.
2. Otherwise, if `achieved_weight_bps` is at least the cycle's `quorum_weight_bps`, the outcome is **adopted**. The comparison is inclusive, so landing exactly on the quorum adopts.
3. Otherwise the outcome is **short**.

An adopted outcome moves the cycle `ENDORSEMENT_ROUND → ADOPTED`, writes `achieved_weight_bps`, stamps `adopted_at` with the logical clock instant, and increments `version` by 1. `ADOPTED` is terminal.

A blocked or short outcome writes `achieved_weight_bps` too, and then branches on the revision budget. If `revision_count` plus one is still within `max_revision_rounds`, the cycle moves `ENDORSEMENT_ROUND → REVISION`, `revision_count` increments by 1, every endorsement of the just-closed round carrying `ENDORSED`, `CONDITIONED` or `VETOED` has its `decision` rewritten to `SUPERSEDED`, and the cycle's `version` increments by 1. The cycle can then loop back through `REVISION → ENDORSEMENT_ROUND` and try again. If instead `revision_count` plus one would exceed `max_revision_rounds`, the cycle moves `ENDORSEMENT_ROUND → FAILED` — `revision_count` is **not** incremented on this edge — with the same supersession of every live current-round endorsement, plus two cascades: every engagement session of the cycle still in `SCHEDULED` moves `SCHEDULED → CANCELLED`, leaving its attendance fields null and permanently excluding it from both the completed-session count and the host occupancy set; and every adaptation project of the cycle whose `screening_status` is `SCREENED_IN` **and** whose `program_status` is `UNPROGRAMMED` moves `SCREENED_IN → SCREENED_OUT`. A project that has already been programmed keeps its `SCREENED_IN` standing when the cycle fails, because its funding has already been committed. Every row touched has its `version` incremented by 1. `FAILED` is terminal.

Because the tally is expensive to reason about in advance, the system also exposes a **read-only projection** of it that writes nothing at all. It reports the cycle's current `round_number`, the `total_active_weight` denominator, the `supporting_weight` and `veto_weight` numerators, the resulting `achieved_weight_bps`, the cycle's configured `quorum_weight_bps`, and a `projected_outcome` string naming which of the three outcomes closing the round right now would produce.

### 3.9. Mutual Aid Across Jurisdictional Boundaries

Shared lifeline assets create shared obligations, and the last workflow in the system is the negotiation of mutual aid between neighbours. A `JurisdictionDelegate` pledges resources by creating a pact on behalf of their own member government, naming the `host_jurisdiction_id` doing the pledging, the `resource_class` being pledged — `CREWS`, `PUMPS`, `GENERATORS` or `COOLING_UNITS` — the total `pledged_units` on offer which must be at least 1, and the `window_start` and `window_end` bounding the availability of the pledge. An optional `max_concurrent_commitments` caps how many existing commitments' windows may overlap a new one; it defaults to 3 and must lie between 1 and 20 inclusive. The host jurisdiction must be `ACTIVE`, and `window_start` must be strictly earlier than `window_end` or the request is rejected with `ERR_INVALID_WINDOW`. A new pact reads `reserved_units` 0, `free_units` equal to `pledged_units`, and `status` `OPEN`.

**Drawing on a pact** is another delegate's act, and it is deliberately cross-jurisdictional: the commitment names the `requesting_jurisdiction_id` receiving the aid — necessarily the caller's own member government — the `asset_id` of the shared lifeline asset the aid supports, the `committed_units` being drawn, the `window_start` and `window_end` of the half-open occupation interval, and the `expected_mutual_aid_pact_version` described in §2.7. `committed_units` must be at least 1. Nine conditions guard the commitment, and they are evaluated in exactly this order:

1. `window_start` must be strictly earlier than `window_end`, or `ERR_INVALID_WINDOW` (HTTP 422).
2. The requesting jurisdiction must be `ACTIVE`, or `ERR_JURISDICTION_NOT_ACTIVE`.
3. The pact's `status` must read `OPEN`; a pact reading `EXHAUSTED` or `EXPIRED` accepts nothing and yields `ERR_PACT_NOT_OPEN`.
4. `expected_mutual_aid_pact_version` must equal the pact's current `version`, or `ERR_STALE_PACT_VERSION` (HTTP 412) — checked before any capacity arithmetic runs.
5. The named lifeline asset's `is_shared` must be true, because only shared assets may be supported across jurisdictional lines; otherwise `ERR_ASSET_NOT_SHARED`.
6. `requesting_jurisdiction_id` must differ from the pact's `host_jurisdiction_id`; a member may not request aid from its own pledge, and the attempt yields `ERR_SELF_AID_NOT_ALLOWED`.
7. The commitment window must lie **inside** the pact window: its `window_start` must be at or after the pact's `window_start` and its `window_end` at or before the pact's `window_end`, or `ERR_AID_WINDOW_OUTSIDE_PACT` (HTTP 422).
8. The maximum **count** of overlapping commitments at any window-start instant must remain strictly below the pact's `max_concurrent_commitments`, or `ERR_AID_CONCURRENCY_LIMIT`. This limit is about how many simultaneous engagements a host can coordinate, not about units: a fourth window covering the same instant as three others is rejected on a pact whose limit is 3 even when the unit total would fit comfortably.
9. The peak **unit load** must be less than or equal to the pact's `pledged_units`; a peak that exceeds the pledge yields `ERR_AID_CAPACITY_EXCEEDED`. A peak landing exactly on `pledged_units` is admitted.

Both of the last two checks read the same candidate set: every commitment already on the pact whose `status` is `COMMITTED` or `FULFILLED`, together with the candidate carried in the request. Commitments in `RELEASED` are excluded and consume no capacity. Occupation intervals are **half-open**: a commitment occupies its `window_start` and every instant up to but not including its `window_end`, so a commitment that ends at exactly the instant another one begins does **not** overlap it. To find the peak, the server takes each distinct `window_start` across the candidate set in ascending order and, at each such instant, sums the `committed_units` of every commitment in the set whose `window_start` is at or before that instant and whose `window_end` is strictly after it; the peak is the largest of those sums. Evaluating the load only at window-start instants is sufficient and exact, because the load can only step upward at a window start. Note carefully that **aggregate** capacity is checked, not pairwise overlap: three commitments that are each individually admissible can collectively breach the pledge at a single instant, and the third one is the one rejected.

A successful commitment reads `status` `COMMITTED` with `released_at` and `fulfilled_at` both null, and it triggers a recomputation of the pact's own ledger. `reserved_units` is set to the **peak** concurrent unit load over the pact's `COMMITTED` and `FULFILLED` commitments — computed by exactly the same procedure as the admission check above, and defined as 0 when that set is empty — and `free_units` becomes `pledged_units` minus `reserved_units`. Because `reserved_units` is a peak and not a running sum, two four-unit commitments whose half-open windows do not overlap reserve four units between them, not eight; two whose windows do overlap reserve eight. The pact's `status` is then re-derived **in this exact order**: `EXPIRED` when the logical clock has reached or passed the pact's `window_end` — this temporal check runs *first*, before any capacity consideration, so an expired pact with no free units reports `EXPIRED` and not `EXHAUSTED`; then `EXHAUSTED` when `free_units` is exactly 0; then `OPEN` otherwise. The pact's `version` increments by 1.

**Releasing** a commitment is the compensating operation, available to a `JurisdictionDelegate` while the commitment's `status` is `COMMITTED`; releasing one already `RELEASED` or `FULFILLED` yields `ERR_COMMITMENT_NOT_ACTIVE`. On success the commitment moves `COMMITTED → RELEASED` and `released_at` is stamped from the logical clock. The pact's `reserved_units` is then recomputed as the peak load over the *surviving* active commitments and `free_units` as `pledged_units` minus that peak, so the pact returns to exactly the values it held before this commitment was admitted, with no drift, and the conservation identity of §2.8 continues to hold. The pact's `status` is re-derived by the same ordered rule, which means a pact that had gone `EXHAUSTED` can revert to `OPEN`. Both the pact's `version` and the commitment's `version` increment by 1.

**Fulfilling** a commitment is the other terminal move and is likewise gated on the commitment being in `COMMITTED`, yielding `ERR_COMMITMENT_NOT_ACTIVE` otherwise. It moves the commitment `COMMITTED → FULFILLED` and stamps `fulfilled_at` from the logical clock. Crucially, fulfilment leaves `reserved_units` and `free_units` **unchanged**, because a fulfilled commitment stays inside the reserved set — the units were actually consumed, so releasing them back to the pledge would be double-counting. Only the commitment's `version` increments by 1. Both `RELEASED` and `FULFILLED` are terminal.

## 4. Endpoint Definitions

Every endpoint is mounted under the `/resilience` prefix. Status codes follow one rule: an operation that brings a genuinely new resource into existence returns **201 Created**, and every other successful operation — retrievals, amendments, state transitions, and operations that mutate an existing resource in place — returns **200 OK**. Unless a workflow in §3 says otherwise, a create or mutate operation returns the created or updated resource in the `data` field of the envelope described in §2.2; list endpoints return an array there together with the pagination fields in `meta`. In the Authorized Role(s) column, **All roles** means all six roles named in §2.1: `RegionalAdministrator`, `HazardAnalyst`, `ProjectSponsor`, `BCAReviewer`, `JurisdictionDelegate` and `EquityOfficer`. The table below is a routing summary only; the request payloads, computed outputs and side effects of each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/resilience/jurisdictions` | Admit a member local government to the regional body | `RegionalAdministrator` |
| GET | `/resilience/jurisdictions` | List member governments | All roles |
| GET | `/resilience/jurisdictions/{jurisdiction_id}` | Retrieve one member government | All roles |
| PATCH | `/resilience/jurisdictions/{jurisdiction_id}` | Amend a member's standing, endorsement weight or social vulnerability score | `RegionalAdministrator` |
| POST | `/resilience/plan-cycles` | Open a periodic regional adaptation plan update cycle | `RegionalAdministrator` |
| GET | `/resilience/plan-cycles` | List plan update cycles | All roles |
| GET | `/resilience/plan-cycles/{plan_cycle_id}` | Retrieve one plan update cycle | All roles |
| POST | `/resilience/plan-cycles/{plan_cycle_id}/open-engagement` | Move the cycle into its community engagement phase | `RegionalAdministrator` |
| POST | `/resilience/plan-cycles/{plan_cycle_id}/open-endorsement-round` | Open a new weighted endorsement round on the cycle | `RegionalAdministrator` |
| POST | `/resilience/plan-cycles/{plan_cycle_id}/close-endorsement-round` | Tally the current round and adopt, revise or fail the cycle | `RegionalAdministrator` |
| GET | `/resilience/plan-cycles/{plan_cycle_id}/endorsement-tally` | Read-only projection of the current round's weighted tally | All roles |
| POST | `/resilience/hazard-profiles` | Record a downscaled climate projection for one jurisdiction and hazard | `HazardAnalyst` |
| GET | `/resilience/hazard-profiles` | List downscaled hazard projections | All roles |
| GET | `/resilience/hazard-profiles/{hazard_profile_id}` | Retrieve one hazard projection | All roles |
| POST | `/resilience/hazard-profiles/{hazard_profile_id}/publish` | Publish a draft projection and supersede the prior published run | `HazardAnalyst` |
| POST | `/resilience/hazard-profiles/{hazard_profile_id}/revisions` | Republish a projection at a higher version, triggering the five-hop freshness cascade | `HazardAnalyst` |
| POST | `/resilience/assets` | Register a lifeline asset, optionally under an upstream dependency | `RegionalAdministrator` |
| GET | `/resilience/assets` | List lifeline assets | All roles |
| GET | `/resilience/assets/{asset_id}` | Retrieve one lifeline asset | All roles |
| PATCH | `/resilience/assets/{asset_id}` | Amend an unranked asset's sharing flag or upstream dependency edge | `RegionalAdministrator` |
| POST | `/resilience/assets/{asset_id}/criticality-ranking` | Rank an asset's failure consequence, tier and dependency depth | `HazardAnalyst` |
| POST | `/resilience/vulnerability-assessments` | Open a vulnerability assessment of one receptor class against one projection | `HazardAnalyst` |
| GET | `/resilience/vulnerability-assessments` | List vulnerability assessments | All roles |
| GET | `/resilience/vulnerability-assessments/{assessment_id}` | Retrieve one vulnerability assessment | All roles |
| POST | `/resilience/vulnerability-assessments/{assessment_id}/assess` | Score an assessment under its declared method variant | `HazardAnalyst` |
| POST | `/resilience/projects` | Propose an adaptation project into a plan update cycle | `ProjectSponsor` |
| GET | `/resilience/projects` | List adaptation projects | All roles |
| GET | `/resilience/projects/{project_id}` | Retrieve one adaptation project | All roles |
| PATCH | `/resilience/projects/{project_id}` | Amend an unprogrammed project's prerequisite or indicator definition | `ProjectSponsor` |
| POST | `/resilience/projects/{project_id}/screen` | Run the cost stack and strategy screen, screening the project in or out | `RegionalAdministrator` |
| POST | `/resilience/projects/{project_id}/asset-links` | Attribute avoided annual loss at a protected lifeline asset | `ProjectSponsor` |
| GET | `/resilience/asset-links` | List project-to-asset benefit attributions | All roles |
| GET | `/resilience/asset-links/{link_id}` | Retrieve one project-to-asset benefit attribution | All roles |
| POST | `/resilience/projects/{project_id}/analyses` | Prepare a benefit-cost analysis under a chosen method variant | `ProjectSponsor` |
| GET | `/resilience/analyses` | List benefit-cost analyses | All roles |
| GET | `/resilience/analyses/{analysis_id}` | Retrieve one benefit-cost analysis | All roles |
| POST | `/resilience/analyses/{analysis_id}/certify` | Independently certify a draft benefit-cost analysis | `BCAReviewer` |
| POST | `/resilience/analyses/{analysis_id}/reject` | Independently reject a draft benefit-cost analysis | `BCAReviewer` |
| POST | `/resilience/projects/{project_id}/withdraw` | Withdraw a programmed project and release its capital | `ProjectSponsor` |
| POST | `/resilience/projects/{project_id}/grant-submission` | Submit a grant application for a programmed project | `ProjectSponsor` |
| POST | `/resilience/projects/{project_id}/grant-award` | Record the grant award on a submitted project | `RegionalAdministrator` |
| POST | `/resilience/projects/{project_id}/equity-waiver` | Waive the capital program's equity benefit floor for one project | `EquityOfficer` |
| POST | `/resilience/projects/{project_id}/indicator-reports` | File a periodic implementation indicator report | `ProjectSponsor` |
| POST | `/resilience/capital-programs` | Open a regional capital program for a fiscal year | `RegionalAdministrator` |
| GET | `/resilience/capital-programs` | List capital programs | All roles |
| GET | `/resilience/capital-programs/{program_id}` | Retrieve one capital program | All roles |
| POST | `/resilience/capital-programs/{program_id}/allocations` | Commit capital to a certified project and recompute the funding ledger | `RegionalAdministrator` |
| POST | `/resilience/plan-cycles/{plan_cycle_id}/engagement-sessions` | Schedule a community engagement session hosted by a member | `JurisdictionDelegate` |
| GET | `/resilience/engagement-sessions` | List community engagement sessions | All roles |
| GET | `/resilience/engagement-sessions/{session_id}` | Retrieve one engagement session | All roles |
| POST | `/resilience/engagement-sessions/{session_id}/complete` | Record attendance and the community's preferred strategy | `JurisdictionDelegate` |
| POST | `/resilience/plan-cycles/{plan_cycle_id}/endorsements` | Cast a weighted endorsement decision in the open round | `JurisdictionDelegate` |
| GET | `/resilience/endorsements` | List endorsements | All roles |
| GET | `/resilience/endorsements/{endorsement_id}` | Retrieve one endorsement | All roles |
| POST | `/resilience/mutual-aid-pacts` | Pledge a class of mutual aid resources over an availability window | `JurisdictionDelegate` |
| GET | `/resilience/mutual-aid-pacts` | List mutual aid pacts | All roles |
| GET | `/resilience/mutual-aid-pacts/{pact_id}` | Retrieve one mutual aid pact | All roles |
| POST | `/resilience/mutual-aid-pacts/{pact_id}/commitments` | Draw units from a neighbour's pact for a shared lifeline asset | `JurisdictionDelegate` |
| GET | `/resilience/mutual-aid-commitments` | List mutual aid commitments | All roles |
| GET | `/resilience/mutual-aid-commitments/{commitment_id}` | Retrieve one mutual aid commitment | All roles |
| POST | `/resilience/mutual-aid-commitments/{commitment_id}/release` | Release a committed draw back to the pledge | `JurisdictionDelegate` |
| POST | `/resilience/mutual-aid-commitments/{commitment_id}/fulfill` | Mark a committed draw as consumed | `JurisdictionDelegate` |
| POST | `/resilience/_clock/set_current_utc` | Advance the server's logical clock to a supplied instant | `RegionalAdministrator` |

## 5. Error Code Catalogue

Every failure mode in the system is reported with one of the identifiers below, returned in the `error_id` field of the error envelope described in §2.2 and paired with the HTTP status shown here. The precedence in which these identifiers are selected when more than one condition holds is specified by the validation ladder in §2.5 and by the per-workflow orderings in §3.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNKNOWN_ROLE` | 403 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_JURISDICTION_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_PLAN_CYCLE_NOT_FOUND` | 404 |
| `ERR_HAZARD_PROFILE_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_LINK_NOT_FOUND` | 404 |
| `ERR_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ENDORSEMENT_NOT_FOUND` | 404 |
| `ERR_PACT_NOT_FOUND` | 404 |
| `ERR_COMMITMENT_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_ACTIVE` | 409 |
| `ERR_PLAN_CYCLE_STATE_INVALID` | 409 |
| `ERR_HAZARD_PROFILE_ALREADY_PUBLISHED` | 409 |
| `ERR_HAZARD_PROFILE_NOT_PUBLISHED` | 409 |
| `ERR_ASSESSMENT_NOT_PENDING` | 409 |
| `ERR_ASSET_ALREADY_RANKED` | 409 |
| `ERR_PROJECT_ALREADY_SCREENED` | 409 |
| `ERR_PROJECT_NOT_SCREENED_IN` | 409 |
| `ERR_PROJECT_ALREADY_PROGRAMMED` | 409 |
| `ERR_PROJECT_NOT_PROGRAMMED` | 409 |
| `ERR_ANALYSIS_NOT_DRAFT` | 409 |
| `ERR_BCA_ALREADY_CERTIFIED` | 409 |
| `ERR_BCA_NOT_CERTIFIED` | 409 |
| `ERR_SESSION_NOT_SCHEDULED` | 409 |
| `ERR_COMMITMENT_NOT_ACTIVE` | 409 |
| `ERR_PACT_NOT_OPEN` | 409 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_STALE_PACT_VERSION` | 412 |
| `ERR_EQUITY_FLOOR_NOT_MET` | 409 |
| `ERR_ASSET_NOT_SHARED` | 409 |
| `ERR_SELF_AID_NOT_ALLOWED` | 409 |
| `ERR_ASSET_DEPENDENCY_CYCLE` | 409 |
| `ERR_PROJECT_PREREQUISITE_CYCLE` | 409 |
| `ERR_DUPLICATE_JURISDICTION_CODE` | 409 |
| `ERR_DUPLICATE_ENDORSEMENT` | 409 |
| `ERR_DUPLICATE_ASSET_LINK` | 409 |
| `ERR_NO_ASSESSED_VULNERABILITY` | 409 |
| `ERR_NO_LINKED_ASSETS` | 409 |
| `ERR_ASSET_RANKING_REQUIRED` | 409 |
| `ERR_PREREQUISITE_NOT_AWARDED` | 409 |
| `ERR_ENGAGEMENT_INCOMPLETE` | 409 |
| `ERR_NO_SCREENED_PROJECTS` | 409 |
| `ERR_INDICATOR_NOT_DEFINED` | 409 |
| `ERR_SESSION_WINDOW_CONFLICT` | 409 |
| `ERR_AID_CONCURRENCY_LIMIT` | 409 |
| `ERR_AID_CAPACITY_EXCEEDED` | 409 |
| `ERR_PROGRAM_FUNDS_EXCEEDED` | 409 |
| `ERR_BCR_BELOW_FLOOR` | 409 |
| `ERR_GRANT_ON_HOLD` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_ATTENDANCE_MISMATCH` | 422 |
| `ERR_CONDITION_NOTE_REQUIRED` | 422 |
| `ERR_AID_WINDOW_OUTSIDE_PACT` | 422 |
| `ERR_ALLOCATION_EXCEEDS_PROJECT_COST` | 422 |

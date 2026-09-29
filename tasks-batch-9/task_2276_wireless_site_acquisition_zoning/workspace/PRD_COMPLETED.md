# Wireless Site Acquisition & Zoning API — Product Requirements Document

## 1. Introduction

Every new cell site begins as a circle on a propagation map. Radio-frequency design hands the real-estate organization a **search ring** — a centre point, a radius, an antenna height, and a coverage or capacity objective — and expects a live site inside it. What follows is one of the least forgiving workflows in telecommunications: a candidate structure must be found, its landlord persuaded, a ground lease negotiated across many rounds, a zoning entitlement won from a jurisdiction that may demand photo simulations and public hearings, a TIA-222 loading analysis passed (or a tower modification designed, peer-reviewed and certified), a NEPA and Section 106 environmental record closed with tribal consultation where it applies, a construction permit issued before it expires, and power and fiber crews scheduled against finite provider capacity. Any one of these can fail late and unwind everything downstream of it.

This API is the system of record for that pipeline. It exists because the failure modes are structural rather than clerical: a structural analysis that fails must not leave a live zoning application and booked fiber crews behind it; a blacklisted landlord must not leave an executed lease standing; a site selected for construction must not remain selected after its permit expires. The specification therefore treats consistency as a product feature — parent rollups, cascading withdrawals and compensating actions are described here with the same precision as the endpoints themselves.

Two further constraints shape the design. First, the program is money-constrained: modification capex is committed against a ring budget, and negotiated rent is measured against a market benchmark, so both are computed with pinned rounding order rather than left to implementation taste. Second, the program is time-constrained and time is a *supplied* quantity: all temporal reasoning runs against a server-owned logical clock so that shot clocks, tolling, permit expiry and crew windows can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply across the whole API. Where §3 describes what the business does, this section describes the shape every request and response takes and the order in which the server reasons about them.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or empty, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the header is well formed but the role is not authorized for the target operation, the rejection is `ERR_UNAUTHORIZED` (403).

The seven roles are `RfEngineer`, `SiteAcquisitionAgent`, `ZoningPlanner`, `StructuralEngineer`, `EnvironmentalReviewer`, `ConstructionManager`, and `ProgramDirector`. Their responsibilities divide as follows. An `RfEngineer` defines search rings from RF design objectives and scores candidates against coverage and capacity targets. A `SiteAcquisitionAgent` registers landlords, identifies candidate sites, runs landlord outreach and negotiates lease terms, and may only act on candidates they own. A `ZoningPlanner` registers jurisdictions and drives entitlement: applications, visual simulations, completeness determinations, hearings and decisions. A `StructuralEngineer` performs TIA-222 loading analyses and authors or peer-reviews modification designs. An `EnvironmentalReviewer` runs NEPA and Section 106 screening, the public-notice branch, and tribal consultation. A `ConstructionManager` files and manages construction permits, registers utility providers, coordinates backhaul crews, marks candidates build-ready and records on-air activation. A `ProgramDirector` holds program authority: setting the logical clock, executing leases negotiated by others, managing landlord standing, selecting sites under optimistic concurrency control, declaring deemed-granted entitlements and owning on-air planning.

**Identity semantics.** All seven roles carry *opaque* identity. When `X-User-Role` is `RfEngineer`, `SiteAcquisitionAgent`, `ZoningPlanner`, `StructuralEngineer`, `EnvironmentalReviewer`, `ConstructionManager` or `ProgramDirector`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any resource's `id`. What the server does instead is *record* and *compare against recorded* operator identifiers. A candidate carries `owning_agent_user_id`, supplied when the candidate is created; when a `SiteAcquisitionAgent` acts on a candidate or its lease, the server compares `X-User-ID` to that stored value and rejects a mismatch with `ERR_NOT_CANDIDATE_OWNER` (403). A lease carries `negotiating_agent_user_id`, a structural analysis carries `performed_by_user_id`, a modification design carries `designed_by_user_id`, and a zoning application carries `filed_by_user_id` — each supplied as an input field, each an opaque operator identifier rather than a foreign key. On certification the server writes the acting `X-User-ID` into the design's `certified_by_user_id`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`, followed by twenty random uppercase-alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is the real wall-clock instant at which the response was assembled, and is the one timestamp in the system that does not read the logical clock of §2.5.
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

Collection reads are paginated through two query parameters. `limit` sets the maximum number of records returned; it defaults to 10, may not be less than 1, and may not exceed 100. `offset` sets how many records to skip and defaults to 0; negative values are not accepted. A `limit` outside the range 1 through 100, a negative `offset`, or a `limit` or `offset` that is not a base-ten integer literal, is rejected with `ERR_INVALID_PAGINATION` (400).

Unless a specific endpoint states otherwise, every list response is ordered by `created_at` ascending; because `created_at` is stamped from the logical clock, records sharing an identical `created_at` are further ordered by the sequence in which the server created them. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`.

Collections also accept domain filters, all of which match the record field of the same name, compared as a string against the textual form of the stored value; a filter value of `null` or of the empty string matches records whose field is null, which is how a ring with no selection is found, and query parameters other than those listed below are ignored. Search rings may be filtered by `market_code`, `status` and `selected_candidate_id` — the last of these acting as the reverse lookup from a chosen candidate back to its ring. Candidates may be filtered by `search_ring_id`, `landlord_id`, `jurisdiction_id`, `acquisition_status` and `feasibility_status`. Leases accept `candidate_id`, `landlord_id` and `status`. Zoning applications accept `candidate_id` and `status`. Structural analyses accept `candidate_id`, `status` and `result`. Modification designs accept `structural_analysis_id` and `status`. Environmental reviews accept `candidate_id` and `status`. Construction permits accept `candidate_id` and `status`. Backhaul orders accept `candidate_id`, `provider_id`, `order_type` and `status`. On-air plans accept `search_ring_id`, `status` and `risk_band`.

### 2.4. Common Resource Properties

Every resource in this system — search rings, landlords, jurisdictions, candidates, lease agreements, zoning applications, structural analyses, modification designs, environmental reviews, construction permits, utility providers, backhaul orders and on-air plans — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. There is no type prefix and no client-supplied identifier.
- `created_at` (string): the ISO 8601 UTC instant at which the record was created — read from the logical clock of §2.5, never from wall-clock time — with three fractional digits.
- `updated_at` (string): the ISO 8601 UTC instant of the most recent mutation, read from that same logical clock, in the same format.
- `version` (integer): a counter that stands at 1 on a newly created record and increments by one on every mutation of that record.

No resource in this system omits `updated_at` or `version`. A write that leaves every field at the value it already held is not a mutation: it succeeds, returns the resource, and moves neither `updated_at` nor `version`. Any change the server makes to a record — including a change to a *computed* field such as a ring's `committed_capex_usd`, a landlord's `executed_lease_count`, a provider's `committed_crew_days` or a candidate's `feasibility_status` — is a mutation of that record: it refreshes `updated_at` and increments `version` on the record that changed. This matters directly for concurrency, because a cascade that touches a parent record moves that parent's `version` even though the client never addressed the parent.

### 2.5. The Logical Clock

All temporal reasoning in this system — shot clocks, tolling, hearing cadence, permit expiry, crew windows, forecast horizons and every "not in the future" check — reads a single server-owned **logical clock**, never wall-clock time. Before the clock has been set for the first time it reads exactly `2026-08-01T00:00:00Z`; this startup default is mandatory and the server never falls back to real time. A `ProgramDirector` moves the clock by supplying a `to_iso8601` instant, which may lie before the clock's current reading as freely as after it. Moving the clock mutates no entity; in particular, permit expiry is evaluated lazily, at the moment a permit is next read or relied upon, rather than eagerly when the clock advances.

Date arithmetic is performed in whole UTC days unless stated otherwise. Where a rule counts the days between two instants, it counts whole UTC days and discards any partial day (a floor).

### 2.6. Monetary Precision and Rounding Order

Money in this system is rent, filing fees and modification capex, and all three are stored to exactly two decimal places using **round half up**. That rule governs the figures the server computes; money arriving in a request body is stored exactly as the client sent it, without re-rounding. Where a calculation has several rounding points, the order of those roundings is part of the contract and is pinned in §3 for each formula. Two cases deserve advance warning because the naive reading is wrong:

- Committed rent is computed by rounding **each lease year to cents first and then summing the rounded years**. Summing unrounded annual figures and rounding once at the end is explicitly incorrect and will produce a different stored value.
- The zoning filing fee's expedite rate is keyed on the **pre-expedite subtotal**, not on the final total. Re-deriving the tier from the final total — which the expedite fee itself has inflated — is explicitly incorrect.

Scores are likewise stored to two decimal places with round half up, and where a score is built from weighted components those components remain unrounded until the single final rounding. Whole-day quantities (`tolled_days`, `crew_days`, `variance_days`, `reset_count`, review-day counts) are integers.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, because each one legitimately supersedes work a previous writer performed and would therefore silently discard state that the current client never observed.

Creating a structural analysis requires a non-optional `expected_candidate_version` field carrying the client's last observed `version` of the target candidate. A new analysis supersedes the candidate's prior analysis and rewrites the candidate's `feasibility_status`, so if `expected_candidate_version` does not equal the candidate's current `version`, the request is rejected with `ERR_STALE_CANDIDATE_VERSION` (412).

Selecting the winning site on a search ring requires a non-optional `expected_search_ring_version` field carrying the client's last observed `version` of the ring. Selection commits capex against a candidate pool and may supersede an earlier selection that a reopen undid, so if `expected_search_ring_version` does not equal the ring's current `version`, the request is rejected with `ERR_STALE_RING_VERSION` (412).

No other endpoint accepts a version field, and none applies a version check. Clients read the current `version` of a ring or a candidate from the corresponding single-resource read.

### 2.8. Path Resolution and Market Alignment

Identifiers in a URL path are resolved left to right, and the first identifier that does not resolve determines the 404 that comes back: `ERR_SEARCH_RING_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_ZONING_APPLICATION_NOT_FOUND`, `ERR_STRUCTURAL_ANALYSIS_NOT_FOUND`, `ERR_MODIFICATION_DESIGN_NOT_FOUND`, `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_UTILITY_PROVIDER_NOT_FOUND`, `ERR_BACKHAUL_ORDER_NOT_FOUND` or `ERR_ON_AIR_PLAN_NOT_FOUND`. Identifiers supplied in a request body are resolved after the path and in the order in which the receiving record declares them, so a create whose payload names two unknown records reports the first-declared one. Creation payloads that reference other records are the candidate, lease, zoning application, structural analysis, modification design, environmental review, construction permit, backhaul order and on-air plan creates.

Beyond mere existence, the program enforces **market alignment**. A search ring, a landlord and a jurisdiction each carry a `market_code`. A candidate binds one ring to one landlord and one jurisdiction, and both the landlord's `market_code` and the jurisdiction's `market_code` must equal the ring's `market_code`; otherwise the candidate is refused with `ERR_MARKET_MISMATCH` (409). A utility provider also carries a `market_code` recording the market it serves.

### 2.9. Validation Precedence

Many operations are guarded by several checks at once, and which error a client sees is determined by a single, system-wide precedence order. Checks are evaluated in the order listed; the first failing check produces the response and later checks are not reached. Where a tier names the operations it guards, that enumeration is exhaustive.

1. Header authentication — `ERR_UNAUTHENTICATED`, on every endpoint.
2. Role authorization — `ERR_UNAUTHORIZED`, on every endpoint.
3. Request-body shape: every required field present — including a field that is required only for the particular `action` or `outcome` requested, such as `counter_rent_usd`, `rejection_reason`, `hearing_date` and `delivered_date`, whose absence is likewise an `ERR_INVALID_REQUEST` raised at this tier and therefore ahead of any path lookup — no unknown fields, correct types, enum members drawn from the declared set, and numeric bounds respected — `ERR_INVALID_REQUEST`, on every write endpoint.
4. Pagination bounds — `ERR_INVALID_PAGINATION`, on every collection read.
5. Existence of path identifiers, left to right — the matching 404 from §2.8, on every endpoint carrying a path identifier.
6. Existence of body identifiers, in declaration order — the matching 404, on the nine create operations named in §2.8.
7. Crew-window well-formedness — `ERR_INVALID_WINDOW`, on backhaul order creation.
8. Market alignment — `ERR_MARKET_MISMATCH`, on candidate creation.
9. Landlord agreement between a lease and its candidate — `ERR_LANDLORD_MISMATCH`, on lease creation.
10. Candidate ownership — `ERR_NOT_CANDIDATE_OWNER`, on exactly four operations: updating a candidate's survey inputs, recording an outreach event, drafting a lease, and recording or accepting a negotiation round.
11. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, on exactly two operations: lease execution and modification-design peer review.
12. Landlord outreach opt-out — `ERR_LANDLORD_OPTED_OUT`, on exactly two operations: recording an outreach event and drafting a lease.
13. Optimistic concurrency — `ERR_STALE_CANDIDATE_VERSION` on structural-analysis creation and `ERR_STALE_RING_VERSION` on site selection.
14. Ring openness — `ERR_RING_NOT_OPEN`, on exactly two operations: RF qualification and site selection.
15. Ring transition state (opening requires `DRAFT`, reopening requires `SITE_SELECTED`) — `ERR_INVALID_RING_STATE`.
16. Candidate dual-dimension state — `ERR_INVALID_CANDIDATE_STATE`, on exactly five operations: recording an outreach event, RF qualification, marking build-ready, creating a structural analysis, and updating survey inputs.
17. Lease state — `ERR_INVALID_LEASE_STATE`, on negotiation rounds, execution and termination.
18. Zoning application state — `ERR_INVALID_ZONING_STATE`, on exactly six operations: attaching a visual simulation, submitting, recording a completeness determination, any hearing action, recording a decision, and declaring deemed-granted.
19. Backing-analysis supersession — `ERR_ANALYSIS_SUPERSEDED`, on exactly two operations: modification-design creation and any peer-review action.
20. Structural-analysis state — `ERR_INVALID_ANALYSIS_STATE`, on analysis completion.
21. Modification-design state, including the requirement that the backing analysis result is `PASS_WITH_MOD` before a design may be submitted for review — `ERR_INVALID_DESIGN_STATE`, on peer-review actions.
22. Environmental-review state and branch state — `ERR_INVALID_REVIEW_STATE`, on screening and branch completion.
23. Construction-permit state (issuance requires `SUBMITTED`, revocation requires `ISSUED`) — `ERR_INVALID_PERMIT_STATE`.
24. Backhaul-order state — `ERR_INVALID_ORDER_STATE`, on order status actions.
25. On-air plan state, including the requirement that the ring is `SITE_SELECTED` at activation — `ERR_INVALID_PLAN_STATE`, on reforecast, reset and activation; plan creation applies no plan-state check of its own.
26. Environmental clearance — `ERR_ENVIRONMENTAL_NOT_CLEARED`, on exactly two operations: marking build-ready and permit issuance.
27. Tribal response window — `ERR_TRIBAL_RESPONSE_WINDOW_OPEN`, on branch completion.
28. An issued permit exists — `ERR_PERMIT_NOT_ISSUED`, on marking build-ready.
29. That issued permit has not expired — `ERR_PERMIT_EXPIRED`, on marking build-ready.
30. Entitlement reached — `ERR_ZONING_NOT_APPROVED`, on permit issuance.
31. Landlord standing — `ERR_LANDLORD_NOT_IN_GOOD_STANDING`, on exactly two operations: the opening `SUBMIT` negotiation round and lease execution.
32. An executed lease exists — `ERR_LEASE_NOT_EXECUTED`, on zoning submission.
33. Build readiness of the selected candidate — `ERR_CANDIDATE_NOT_BUILD_READY`, on on-air activation.
34. Backhaul delivery of the selected candidate — `ERR_BACKHAUL_NOT_DELIVERED`, on on-air activation.
35. Visual-simulation minimum — `ERR_VISUAL_SIMULATION_REQUIRED`, on zoning submission.
36. Continuance ceiling — `ERR_CONTINUANCE_LIMIT_REACHED`, on the `CONTINUE` hearing action.
37. Negotiation-round ceiling — `ERR_NEGOTIATION_ROUND_LIMIT`, on the `SUBMIT`, `COUNTER` and `REVISE` round actions.
38. One live zoning application per candidate — `ERR_DUPLICATE_ZONING_APPLICATION`, on zoning-application creation.
39. One live environmental review per candidate — `ERR_DUPLICATE_ENVIRONMENTAL_REVIEW`, on environmental-review creation.
40. Hearing cadence within a jurisdiction — `ERR_HEARING_WINDOW_CONFLICT`, on the `SCHEDULE` and `CONTINUE` hearing actions.
41. Provider crew capacity — `ERR_PROVIDER_CAPACITY_EXCEEDED`, on backhaul order creation.
42. Shot clock exhausted — `ERR_SHOT_CLOCK_NOT_EXPIRED`, on declaring deemed-granted.
43. Hearing date not in the past — `ERR_HEARING_DATE_IN_PAST`, on the `SCHEDULE` and `CONTINUE` hearing actions.
44. Hearing date reached — `ERR_HEARING_NOT_YET_HELD`, on the `HOLD` hearing action.
45. Supplied as-of dates not in the future — `ERR_DATE_IN_FUTURE`, on exactly five operations: lease execution, recording a zoning decision, permit issuance, the `DELIVER` order action, and on-air activation.
46. Decision date ordering — `ERR_DECISION_DATE_INVALID`, on recording a zoning decision.
47. New target date in the future — `ERR_TARGET_DATE_IN_PAST`, on resetting an on-air plan's target.
48. Ring capex budget — `ERR_CAPEX_BUDGET_EXCEEDED`, on the `CERTIFY` peer-review action.
49. Rent variance ceiling — `ERR_RENT_VARIANCE_EXCEEDED`, on the `ACCEPT` round action.
50. A non-empty selector pool — `ERR_NO_ELIGIBLE_CANDIDATE`, on exactly three operations unconditionally: site selection, on-air plan creation, and reforecast; a reset and the computed forecast read reach the same error only in the narrower case where the pool is empty *and* the plan records no earlier driver candidate to fall back on, as §3.9 describes.

### 2.10. Cascade Integrity Across the Program

Two long cascades run through this system, and both are described end to end here because each link mutates a record the client did not address.

**The feasibility cascade.** When a structural analysis completes with a failing result, the candidate's `feasibility_status` becomes `DISQUALIFIED`. That disqualification withdraws every zoning application of that candidate whose status is not already `APPROVED`, `DENIED`, `DEEMED_GRANTED` or `WITHDRAWN`, setting each to `WITHDRAWN`. Each withdrawn application in turn cancels every backhaul order of the same candidate whose status is `REQUESTED` or `SCHEDULED`, setting each to `CANCELLED` and recomputing the affected provider's `committed_crew_days`. The disqualification also recomputes the ring's `candidate_count` and `committed_capex_usd`, and if the disqualified candidate was the ring's `selected_candidate_id`, the ring's `selected_candidate_id` is cleared to null and its `status` returns to `OPEN`. Every record touched along the chain has its own `version` incremented.

**The landlord cascade.** When a landlord's `standing` is set to `BLACKLISTED`, every lease of that landlord whose status is `EXECUTED` becomes `TERMINATED`. Each terminated lease drives its candidate's `acquisition_status` to `RELINQUISHED`. Each relinquished candidate recomputes the ring's `candidate_count` and `committed_capex_usd`, and clears the ring's selection back to `OPEN` with a null `selected_candidate_id` if that candidate had been the selected one. The landlord's `executed_lease_count` is recomputed as part of the same operation.

Rollups are always *recomputed from the underlying rows*, never adjusted incrementally, so that a compensating action leaves the ledger exactly where it started. Reopening a ring after a selection restores the same `committed_capex_usd` the ring had before selection; terminating a lease immediately after executing it leaves the landlord's `executed_lease_count` exactly as it was before the execution.

### 2.11. Segregation of Duties

Two artifacts in this program may not be approved by the person who prepared them. A lease may not be executed by the agent who negotiated it: if the executing `ProgramDirector`'s `X-User-ID` equals the lease's `negotiating_agent_user_id`, the execution is refused with `ERR_SEGREGATION_OF_DUTIES` (403). A modification design may not be certified by its author, nor by the engineer who performed the analysis it rests on: if the certifying `StructuralEngineer`'s `X-User-ID` equals either the design's `designed_by_user_id` or the backing analysis's `performed_by_user_id`, certification is refused with the same error. Rejecting a design is subject to the narrower form of the same principle — the rejecting engineer's `X-User-ID` must differ from `designed_by_user_id`.

## 3. Business Logic & Workflows

### 3.1. Opening a Search Ring

A search ring is the RF design's statement of intent, and an `RfEngineer` creates one by describing the target rather than the site. The payload carries a human-readable `name`, the `market_code` the ring belongs to, the ring centre as `center_lat` and `center_lon` (plain numbers, with no coordinate-range check), an integer `radius_m` of at least 100 metres, and the antenna centreline height the design demands as an integer `required_agl_m`, at least 10 metres. The RF objective itself is declared through `objective_type`, one of `COVERAGE`, `CAPACITY` or `COVERAGE_AND_CAPACITY`, alongside a `target_rsrp_dbm` reference-signal power (a negative dBm figure by convention, though the server bounds it neither above nor below) and a `target_capacity_gbps` backhaul objective greater than zero. Three commercial parameters complete the ring: `market_benchmark_monthly_rent_usd`, the benchmark ground rent for the market, which must be greater than zero; `capex_budget_usd`, the non-negative ceiling on tower modification spend for this ring; and `priority_rank`, an integer expressing RF program priority where 1 is highest.

A new ring begins in `DRAFT` with `candidate_count` at 0, `committed_capex_usd` at 0, `reopen_count` at 0 and `selected_candidate_id` null. The ring's `status` moves `DRAFT → OPEN` when the `RfEngineer` opens it for candidate development; an attempt to open a ring that is not in `DRAFT` is refused with `ERR_INVALID_RING_STATE`. `candidate_count` tracks the number of candidates attached to the ring whose `acquisition_status` is anything other than `RELINQUISHED`, and is recomputed whenever a candidate joins the ring or is relinquished or disqualified.

Later in the ring's life, a `ProgramDirector` moves it `OPEN → SITE_SELECTED` and, if the choice must be undone, back `SITE_SELECTED → OPEN`. The reopen carries a free-text `reason`, increments `reopen_count` by one, clears `selected_candidate_id` to null and recomputes `committed_capex_usd`; it is refused with `ERR_INVALID_RING_STATE` unless the ring is in `SITE_SELECTED`. The terminal state of a ring is `ON_AIR`, which the ring reaches only as a consequence of its on-air plan being activated, moving the ring `SITE_SELECTED → ON_AIR`.

### 3.2. Program Reference Data: Landlords, Jurisdictions and Providers

A `SiteAcquisitionAgent` registers each **landlord** with a `legal_name`, a `contact_email` for outreach, the `market_code` in which the landlord operates, and an `entity_type` drawn from `INDIVIDUAL`, `LLC`, `REIT`, `MUNICIPALITY` and `TRIBAL_AUTHORITY`. The optional `outreach_optout` flag defaults to false; when it is true the landlord has refused contact, and both outreach events and lease drafting against that landlord are refused with `ERR_LANDLORD_OPTED_OUT`. A landlord's `standing` starts at `ACTIVE` and its `executed_lease_count` at 0. `standing` is a `ProgramDirector` concern: they may set it to `ACTIVE`, `SUSPENDED` or `BLACKLISTED`, optionally recording a `reason`; whatever cascade follows, the landlord's own record takes at most one `version` increment for the whole call, and none at all when the standing supplied is the one already stored and the recomputed `executed_lease_count` is unchanged. Only `ACTIVE` standing permits the opening negotiation round or lease execution; anything else is refused with `ERR_LANDLORD_NOT_IN_GOOD_STANDING`. Setting `BLACKLISTED` triggers the landlord cascade described in §2.10. The landlord's `executed_lease_count` is, at all times, the count of that landlord's leases whose status is `EXECUTED` — recomputed after every execution, every termination and every blacklist cascade, and no other status contributes to it.

The `entity_type` value `TRIBAL_AUTHORITY` carries a downstream consequence that reaches beyond real estate: a candidate whose landlord is a tribal authority always requires tribal consultation on its environmental review, regardless of what the jurisdiction demands.

A `ZoningPlanner` registers each **jurisdiction** with a `name`, a `market_code`, and the review calendar the authority actually runs. Three nominal review-day counts, each at least 1, correspond to the three entitlement paths: `by_right_review_days`, `conditional_use_review_days` and `variance_review_days`. `hearing_cadence_days`, at least 1, does double duty — it is the minimum whole-day separation the jurisdiction requires between any two hearing dates it has booked, and it is also the per-continuance schedule penalty applied to risk-adjusted forecasts. `requires_visual_simulation` declares whether photo simulations must be on file before an application may be filed, and `min_visual_simulations` — a non-negative integer which defaults to 2 when omitted — is the count enforced when that flag is true. `max_continuances`, a non-negative integer, caps hearing continuances per application. `historic_district_flag` records that sites in this jurisdiction sit within a historic district, which adds a surcharge to filing fees. `tribal_consultation_required` records that the jurisdiction mandates TCNS tribal consultation on every site. `historical_delay_factor`, at least 1.0, is the observed schedule inflation multiplier the risk-adjusted forecast applies. `appeal_window_days`, non-negative, records how many days after a decision the jurisdiction allows an appeal to be lodged.

A `ConstructionManager` registers each **utility provider** — a power or fiber company — with a `name`, the `market_code` it serves, a `concurrent_crew_capacity` of at least 1 expressing how many orders' crew windows may cover the same UTC day, and a non-negative `quoted_interval_days` recording the lead time the provider quotes for a new order. A provider's `committed_crew_days` begins at 0.

### 3.3. Candidates: Identification, Outreach and RF Qualification

A `SiteAcquisitionAgent` attaches a candidate site to a ring by supplying the ring through `search_ring_id`, the property owner through `landlord_id`, the zoning authority through `jurisdiction_id`, and the opaque agent identifier that will own the record through `owning_agent_user_id`. The structure itself is described by `site_type` — one of `TOWER`, `ROOFTOP` or `RAW_LAND` — its position as `lat` and `lon`, its surveyed `distance_from_center_m` from the ring centre (a non-negative integer), the available antenna centreline height as `agl_m` (a non-negative integer), and `months_to_availability`, the non-negative integer number of months before the site can be occupied. Two RF measurements complete the record: `measured_rsrp_dbm`, the drive-tested reference-signal power in dBm and unbounded in either direction, and `offered_capacity_gbps`, the non-negative backhaul capacity available at the site. Creating the candidate recomputes the ring's `candidate_count` and increments the ring's `version`; it is admitted whatever the ring's `status`, so a ring still in `DRAFT` may accumulate candidates.

A candidate advances along **two independent state dimensions on one record**. `acquisition_status` is the real-estate track and begins at `PROSPECTING`, moving through `OUTREACH_SENT`, `LANDLORD_ENGAGED` and `LEASE_EXECUTED` to the terminal `RELINQUISHED`. `feasibility_status` is the engineering and entitlement track and begins at `UNSCREENED`, moving through `RF_QUALIFIED`, `STRUCTURAL_HOLD`, `STRUCTURALLY_CLEARED`, `ENTITLED` and `BUILD_READY`, with the terminal `DISQUALIFIED`. The two dimensions advance through different operations and neither blocks the other except where a specific rule names the other dimension explicitly. Alongside them the record carries `outreach_event_count` (starting at 0), `environmental_cleared` (starting false), `permit_issued` (starting false), and `rf_qualification_score`, which is null until the candidate is scored.

While a candidate is still `UNSCREENED` on the feasibility dimension, its owning agent may revise the survey inputs, supplying any subset of `distance_from_center_m`, `agl_m`, `months_to_availability`, `measured_rsrp_dbm` and `offered_capacity_gbps`. Once the candidate has left `UNSCREENED`, a survey revision is refused with `ERR_INVALID_CANDIDATE_STATE`, because the score would then rest on inputs that no longer match the screening decision.

**Outreach.** The owning agent records each landlord contact as an outreach event, supplying an `event_type` and an optional `note`. Each recorded event increments `outreach_event_count` by one and increments the candidate's `version`; the response body is the updated candidate, since outreach events are not themselves persisted resources. An `OUTREACH_SENT` event moves the acquisition dimension `PROSPECTING → OUTREACH_SENT` and is only accepted while the candidate is in `PROSPECTING`. A `LANDLORD_REPLY` event moves it `OUTREACH_SENT → LANDLORD_ENGAGED` and is only accepted while the candidate is in `OUTREACH_SENT`. A `LANDLORD_DECLINED` event is accepted while the candidate is in either `OUTREACH_SENT` or `LANDLORD_ENGAGED` and drives the acquisition dimension to `RELINQUISHED` from either state; in both cases it also withdraws every lease of that candidate whose status is `DRAFT`, `SUBMITTED`, `COUNTERED` or `REVISED`, setting each to `WITHDRAWN`, and recomputes the ring's `candidate_count` and `committed_capex_usd`. Every one of these three events additionally requires that the landlord has not opted out and that the acting `X-User-ID` matches `owning_agent_user_id`; a state that does not admit the requested event yields `ERR_INVALID_CANDIDATE_STATE`.

A candidate may also be relinquished without any outreach event at all: when the candidate's `EXECUTED` lease is terminated, the acquisition dimension moves `LEASE_EXECUTED → RELINQUISHED`, the ring's rollups are recomputed, and the ring's selection is cleared back to `OPEN` if this candidate was the selected one.

**RF qualification.** An `RfEngineer` scores an `UNSCREENED` candidate against its ring's objectives, which requires the ring to be `OPEN` — otherwise `ERR_RING_NOT_OPEN`. Scoring is a single-candidate computation: it reads only the candidate named in the request and the ring reached through its `search_ring_id`, and never aggregates over sibling candidates. Four components are computed, each on a 0-to-100 scale and each clamped to that range, and none of them is rounded:

- The **signal component** starts at 50 and adds 5 points for every dBm by which the candidate's `measured_rsrp_dbm` exceeds the ring's `target_rsrp_dbm`; where the measurement is weaker than the target the difference is negative and the same 5-points-per-dBm rate subtracts. The result is clamped to the range 0 through 100.
- The **distance component** is 100 multiplied by the quantity one minus the candidate's `distance_from_center_m` divided by the ring's `radius_m`, clamped to 0 through 100. A candidate at the ring centre scores 100; one at or beyond the ring edge scores 0.
- The **height component** is exactly 100 when the candidate's `agl_m` is greater than or equal to the ring's `required_agl_m`; otherwise it is 100 multiplied by `agl_m` divided by `required_agl_m`, clamped to 0 through 100.
- The **capacity component** is exactly 100 when the ring's `objective_type` is `COVERAGE`, since capacity is then not an objective. For the other two objectives it is 100 multiplied by the candidate's `offered_capacity_gbps` divided by the ring's `target_capacity_gbps`, clamped to 0 through 100.

The four components are then combined with fixed weights that sum to one: 0.35 on the signal component, 0.25 on the distance component, 0.20 on the height component and 0.20 on the capacity component. To that weighted sum a structure bonus is added — 10 points for a `TOWER`, 5 points for a `ROOFTOP` and nothing for `RAW_LAND` — reflecting that existing steel is faster and cheaper to build on than bare ground. From it an availability penalty is subtracted: sites available within the first six months attract no penalty at all, and beyond that grace period 2.5 points are deducted for each additional month in `months_to_availability`; the penalty is never negative, so an early-availability site is not rewarded twice. The resulting figure is clamped to the range 0 through 100 and only then rounded, half up, to two decimal places, and stored as `rf_qualification_score`. There is exactly one rounding step in the whole calculation.

The stored score decides the outcome. A score of at least 55.00 moves the feasibility dimension `UNSCREENED → RF_QUALIFIED`. A score below 55.00 moves it `UNSCREENED → DISQUALIFIED` and runs the same feasibility cascade of §2.10 that a failing structural analysis runs — withdrawing any live zoning application of the candidate (and, where a withdrawal occurred, cancelling that candidate's `REQUESTED` and `SCHEDULED` backhaul orders), recomputing both the ring's `candidate_count` and its `committed_capex_usd`, and clearing the ring's selection if this candidate held it. Either way the score is written and the candidate's `version` increments; the request is not an error in the failing case, because a disqualifying score is a legitimate screening result.

### 3.4. Ground Lease Negotiation, Execution and Committed Rent

The owning `SiteAcquisitionAgent` drafts a ground lease against a candidate, naming the candidate through `candidate_id`, repeating the property owner through `landlord_id` — which must equal the candidate's own landlord, or the draft is refused with `ERR_LANDLORD_MISMATCH` — and recording the opaque negotiator through `negotiating_agent_user_id`. The economics are declared up front: `base_monthly_rent_usd`, the year-one monthly ground rent, greater than zero; an `escalation_type` of `FIXED_PCT`, `CPI_CAPPED` or `FLAT_STEP`; and the three escalation parameters, each defaulting to 0 when omitted — `escalation_pct`, the annual escalation rate expressed as a decimal fraction so that a value of 0.03 raises rent by three percent per year; `escalation_step_usd`, a flat monthly dollar step; and `cpi_cap_pct`, the ceiling that caps escalation under a CPI-linked lease. The term is declared as `initial_term_years`, at least 1, plus `renewal_option_count` and `renewal_term_years`, both non-negative, describing how many renewal options exist and how long each runs. Two further commercial terms complete the draft: `equipment_expansion_sqft`, the non-negative contracted area in square feet within which the carrier may expand its equipment footprint without renegotiating, and `revenue_share_pct`, defaulting to 0, the landlord's share of revenue. A new lease begins in `DRAFT` with `round_count` at 0, `last_counter_rent_usd` null, `execution_date` null, and all three computed money fields — `rent_variance_pct`, `committed_rent_provisional_usd` and `committed_rent_final_usd` — null.

**The negotiation loop.** Rounds are recorded by the owning agent through an `action` and an optional `counter_rent_usd`. `SUBMIT` opens the negotiation and moves the lease `DRAFT → SUBMITTED`; it additionally requires the landlord's `standing` to be `ACTIVE`. `COUNTER` records the landlord's counter-offer and is accepted from either `SUBMITTED` or `REVISED`, moving the lease to `COUNTERED`. `REVISE` records the carrier's revised offer and is accepted only from `COUNTERED`, moving the lease to `REVISED`. The `COUNTERED → REVISED → COUNTERED` cycle may repeat. All three of these actions require `counter_rent_usd` to be present, store it as `last_counter_rent_usd`, increment `round_count` by one, recompute `rent_variance_pct`, and increment the lease's `version`. All three also require that fewer than six rounds have already been recorded; a seventh round is refused with `ERR_NEGOTIATION_ROUND_LIMIT`. An action that the current status does not admit is refused with `ERR_INVALID_LEASE_STATE`.

`rent_variance_pct` measures how far the offer on the table sits from the market. It is 100 multiplied by the difference between the lease's `last_counter_rent_usd` and the ring's `market_benchmark_monthly_rent_usd`, divided by that same `market_benchmark_monthly_rent_usd`, rounded half up to two decimal places. The ring is reached through the lease's candidate and that candidate's `search_ring_id`.

`ACCEPT` closes the negotiation and is accepted from `SUBMITTED`, `COUNTERED` or `REVISED`, moving the lease to `ACCEPTED` from any of the three. It requires that `last_counter_rent_usd` is not null — a null one is refused with `ERR_INVALID_LEASE_STATE` — and it enforces the rent-variance ceiling: the stored, rounded `rent_variance_pct` must not exceed 15.00, with a variance of exactly 15.00 permitted and anything strictly above it refused with `ERR_RENT_VARIANCE_EXCEEDED`. On acceptance the agreed figure becomes the lease's economics — `base_monthly_rent_usd` is overwritten with `last_counter_rent_usd` — and the provisional variant of the committed rent is computed and stored in `committed_rent_provisional_usd`. `ACCEPT` does not increment `round_count`.

**Committed rent.** The committed rent is the sum of annual rent over a horizon, and the annual rent for lease year *y* (counting the first year as year 1) depends on the escalation mechanism. Under `FIXED_PCT` it is `base_monthly_rent_usd` multiplied by 12, multiplied by the quantity one plus `escalation_pct` raised to the power of *y* minus one. Under `CPI_CAPPED` it is the same expression except that the rate compounded is the lesser of `escalation_pct` and `cpi_cap_pct`. Under `FLAT_STEP` there is no compounding at all: the monthly rent for year *y* is `base_monthly_rent_usd` plus `escalation_step_usd` multiplied by *y* minus one, and the annual figure is that monthly rent multiplied by 12.

The rounding order here is pinned and is the single most common way to get this calculation wrong. **Each lease year's annual rent is rounded half up to two decimal places first, and only the rounded per-year figures are summed.** Summing unrounded annual figures and rounding once at the end is explicitly incorrect.

Two variants of the total are produced from that same per-year series. The **provisional** variant, written to `committed_rent_provisional_usd` at acceptance, sums the rounded years 1 through `initial_term_years` and rounds the sum half up to two decimal places; renewal options are ignored and `revenue_share_pct` is not applied. The **final** variant, written to `committed_rent_final_usd` at execution, assumes every renewal option is exercised: its horizon is `initial_term_years` plus `renewal_option_count` multiplied by `renewal_term_years`, it sums the rounded years 1 through that horizon and rounds the sum to two decimal places to obtain a base total, then computes a revenue-share uplift as that base total multiplied by `revenue_share_pct` rounded half up to two decimal places, and finally stores the base total plus the uplift, again rounded half up to two decimal places.

A computed read exposes both variants side by side for the lease's current economics, available to any `SiteAcquisitionAgent` and to the program authority — the read applies no candidate-ownership check of its own. It reports `provisional_total_usd` and `final_total_usd` as just defined, `delta_usd` as the final total minus the provisional total rounded half up to two decimal places, `priced_years` as the full final-variant horizon in years, and the two ends of the per-year series — `first_year_rent_usd`, the rounded annual rent for year 1, and `last_year_rent_usd`, the rounded annual rent for the final year of that horizon.

**Execution and termination.** Only a `ProgramDirector` may execute an `ACCEPTED` lease, and only one who did not negotiate it — the segregation-of-duties rule of §2.11 applies here. Execution also requires the landlord's `standing` to be `ACTIVE`, and it carries an `execution_date` that must not be after the logical clock; a future date is refused with `ERR_DATE_IN_FUTURE`. On success the supplied `execution_date` is stored, the final committed-rent variant is computed into `committed_rent_final_usd`, the lease moves `ACCEPTED → EXECUTED`, the candidate's `acquisition_status` is set to `LEASE_EXECUTED` from whatever state it holds — ordinarily `LANDLORD_ENGAGED`, but the server imposes no precondition on that dimension and merely leaves an already-`RELINQUISHED` candidate alone — and the landlord's `executed_lease_count` is recomputed.

Termination is the compensating action. A `ProgramDirector` terminates an `EXECUTED` lease with a `reason`, moving it `EXECUTED → TERMINATED`; this recomputes the landlord's `executed_lease_count`, drives the candidate's `acquisition_status` to `RELINQUISHED`, and recomputes the ring's `candidate_count` and `committed_capex_usd`. A lease also reaches `TERMINATED` from `EXECUTED` without any client request when its landlord is blacklisted, with the same downstream effects. And a lease in `DRAFT`, `SUBMITTED`, `COUNTERED` or `REVISED` reaches the terminal `WITHDRAWN` when its candidate becomes `RELINQUISHED`. `WITHDRAWN` and `TERMINATED` are both terminal.

### 3.5. Structural Loading and Modification Peer Review

A `StructuralEngineer` opens a TIA-222 loading analysis against a candidate that is either `RF_QUALIFIED` or `STRUCTURALLY_CLEARED` on the feasibility dimension; any other feasibility state is refused with `ERR_INVALID_CANDIDATE_STATE`. The payload names the candidate through `candidate_id`, declares the governing code revision through `analysis_type` — `TIA_222_H` or `TIA_222_G` — and describes the loading case: `existing_load_pct`, the non-negative percentage of structure capacity already consumed; `appurtenance_count`, the non-negative number of new mounts, lines and remote radio units this build adds; `wind_speed_mph`, the design basic wind speed, greater than zero; and `ice_thickness_in`, the non-negative design radial ice thickness in inches. The engineer performing the work is recorded as `performed_by_user_id`, and the request must carry `expected_candidate_version` per §2.7.

Creating an analysis has three effects beyond the new record, which begins in `IN_PROGRESS` with `capacity_utilization_pct` null and `result` at `PENDING`. Any prior analysis of the same candidate is superseded — a prior analysis in `IN_PROGRESS` moves `IN_PROGRESS → SUPERSEDED` and one in `COMPLETED` moves `COMPLETED → SUPERSEDED`, `SUPERSEDED` being terminal. The candidate's `feasibility_status` moves to `STRUCTURAL_HOLD`, whether it was `RF_QUALIFIED` or `STRUCTURALLY_CLEARED` beforehand. And the candidate's `version` increments. This is precisely why the operation is version-guarded: a writer holding a stale view of the candidate would otherwise supersede an analysis it never observed.

**Completing the analysis.** The engineer completes an `IN_PROGRESS` analysis; completing an analysis in any other status is refused with `ERR_INVALID_ANALYSIS_STATE`. Completion computes `capacity_utilization_pct` from the single analysis named in the request — sibling analyses never contribute, since older ones are `SUPERSEDED`. The appurtenance load contributes 1.8 percentage points for each appurtenance in `appurtenance_count`. The wind factor is the ratio of `wind_speed_mph` to a 90-mph baseline, squared. The ice factor is one plus 0.15 for each inch of `ice_thickness_in`. The code factor is 1.00 under `TIA_222_H` and 0.95 under `TIA_222_G`, the older revision being the more permissive of the two. The proposed load is the sum of a fixed 9.5 percentage points for the new antenna array and the appurtenance load, that sum multiplied by the wind factor and then by the ice factor. `capacity_utilization_pct` is the sum of `existing_load_pct` and the proposed load, multiplied by the code factor, rounded half up to two decimal places — a single rounding at the very end, with every intermediate factor left unrounded.

The stored utilization classifies the `result`. A utilization of 85.00 or less is a `PASS`. A utilization above 85.00 but no greater than 100.00 is a `PASS_WITH_MOD` — the structure can carry the build, but only after reinforcement. Anything above 100.00 is a `FAIL`. Completion sets `status` to `COMPLETED` and then acts on the candidate: a `PASS` moves the candidate `STRUCTURAL_HOLD → STRUCTURALLY_CLEARED`; a `FAIL` moves it `STRUCTURAL_HOLD → DISQUALIFIED` and starts the feasibility cascade of §2.10 — the candidate's live zoning applications are withdrawn, that candidate's open backhaul orders are cancelled, the affected providers' `committed_crew_days` are recomputed, the ring's `candidate_count` and `committed_capex_usd` are recomputed, and the ring's selection is cleared if this candidate held it. A `PASS_WITH_MOD` leaves the candidate in `STRUCTURAL_HOLD`: it takes a certified modification design to clear it. All three candidate effects are conditional on the candidate still being in `STRUCTURAL_HOLD` when the analysis completes; one that a cascade has since moved elsewhere is left exactly as it is, whatever the result, while the analysis itself still records its utilization, result and `COMPLETED` status.

**Modification designs.** Against a `COMPLETED` analysis a `StructuralEngineer` creates a modification design, naming the analysis through `structural_analysis_id`, declaring the `scope` as `REINFORCEMENT`, `MOUNT_UPGRADE` or `TOWER_REPLACEMENT`, stating the capex as `estimated_cost_usd` greater than zero, and recording the author as `designed_by_user_id`. A design created against an analysis that is `IN_PROGRESS` or `SUPERSEDED` is refused with `ERR_ANALYSIS_SUPERSEDED`; the same refusal applies to any peer-review action whose backing analysis is not `COMPLETED`. A new design begins in `DRAFT` with `revision_count` at 0, `certified_by_user_id` null and `rejection_reason` null.

The peer-review cycle is driven by an `action` and, for one of them, a `rejection_reason`. `SUBMIT` moves the design `DRAFT → PEER_REVIEW` and additionally requires the backing analysis's `result` to be `PASS_WITH_MOD`; submitting a design whose analysis passed outright, or whose analysis failed, is refused with `ERR_INVALID_DESIGN_STATE`, as is any action the current design status does not admit. `REJECT` moves the design `PEER_REVIEW → REJECTED`, requires `rejection_reason` to be present, stores it, and requires the acting `X-User-ID` to differ from `designed_by_user_id`. `REVISE` moves the design `REJECTED → DRAFT`, increments `revision_count` by one and clears `rejection_reason` back to null, so the `DRAFT → PEER_REVIEW → REJECTED → DRAFT` loop may run as many times as the reviewers require. `CERTIFY` moves the design `PEER_REVIEW → CERTIFIED`, which is terminal; it enforces both halves of the segregation-of-duties rule from §2.11, writes the acting `X-User-ID` into `certified_by_user_id`, recomputes the ring's `committed_capex_usd`, and clears the candidate `STRUCTURAL_HOLD → STRUCTURALLY_CLEARED` when the candidate is in `STRUCTURAL_HOLD`.

**The ring capex ledger.** A ring's `committed_capex_usd` is the sum of `estimated_cost_usd` across every modification design that is `CERTIFIED`, whose backing analysis is `COMPLETED`, and whose candidate belongs to that ring and is neither `RELINQUISHED` on the acquisition dimension nor `DISQUALIFIED` on the feasibility dimension — over all time, with the sum rounded half up to two decimal places. Because it is a sum, the order in which designs are visited does not matter. Certification is gated on that ledger: if the recomputed `committed_capex_usd` including the design being certified would exceed the ring's `capex_budget_usd`, certification is refused with `ERR_CAPEX_BUDGET_EXCEEDED`; a recomputed total exactly equal to the budget is permitted. Because the ledger is always recomputed from the qualifying rows rather than adjusted incrementally, a candidate later relinquished or disqualified silently releases its certified capex back to the ring's budget.

### 3.6. Zoning Entitlement: Filing, Tolling, Hearings and the Shot Clock

A `ZoningPlanner` prepares a zoning application for a candidate, naming it through `candidate_id`, choosing the entitlement path through `application_type` — `BY_RIGHT`, `CONDITIONAL_USE` or `VARIANCE` — and recording the filer as `filed_by_user_id`. The jurisdiction is not supplied: it is read through the candidate's `jurisdiction_id`. A candidate may carry only one live application at a time; if it already has an application whose status is anything other than `WITHDRAWN` or `DENIED`, the creation is refused with `ERR_DUPLICATE_ZONING_APPLICATION`. A new application begins in `PREPARING` with `visual_simulation_count` at 0, `tolled_days` at 0, `continuance_count` at 0, `hearings_held_count` at 0, and `submitted_date`, `hearing_date`, `incomplete_since_date`, `shot_clock_deadline_date`, `zoning_fee_total_usd` and `decision_date` all null.

**Visual simulations.** While the application is `PREPARING`, the planner attaches photo simulations one at a time, each described by a `view_angle_deg` bearing and a `photo_reference` locating the rendered image. Each attachment increments `visual_simulation_count` by one and returns the updated application; individual simulations are not persisted as resources of their own, so neither `view_angle_deg` nor `photo_reference` is retained or bounded. Attaching a simulation to an application that has left `PREPARING` is refused with `ERR_INVALID_ZONING_STATE`.

**Filing.** Submission moves the application `PREPARING → SUBMITTED` and requires two things of the world outside the application. The candidate's `acquisition_status` must be `LEASE_EXECUTED` — a carrier does not file for entitlement on land it has not secured — and a candidate without an executed lease yields `ERR_LEASE_NOT_EXECUTED`. And where the jurisdiction's `requires_visual_simulation` is true, the application's `visual_simulation_count` must be at least the jurisdiction's `min_visual_simulations`; a shortfall yields `ERR_VISUAL_SIMULATION_REQUIRED` (422). Submission stamps `submitted_date` with the logical clock, prices the filing fee into `zoning_fee_total_usd`, and computes the initial `shot_clock_deadline_date`.

**The filing fee** is assembled in exactly four steps, in this order, with no re-derivation and no iteration. Step one builds a subtotal: a base fee determined by `application_type` — 1500.00 for `BY_RIGHT`, 3200.00 for `CONDITIONAL_USE`, 4800.00 for `VARIANCE` — plus 250.00 for each simulation counted in `visual_simulation_count`, plus a historic-district surcharge of 900.00 when the jurisdiction's `historic_district_flag` is true and nothing when it is false. Step two selects an expedite rate **from that step-one subtotal**: a subtotal of 6000 or more takes 0.12, a subtotal of at least 4000 but below 6000 takes 0.08, and a subtotal below 4000 takes 0.04. Step three computes the expedite fee as the subtotal multiplied by that rate, rounded half up to two decimal places. Step four stores `zoning_fee_total_usd` as the subtotal plus the expedite fee, rounded half up to two decimal places. Re-deriving the tier from the step-four total — which the expedite fee itself has inflated — is explicitly wrong and will misprice applications that sit near a tier boundary.

**The shot clock.** `shot_clock_deadline_date` is the `submitted_date` advanced by the number of review days the jurisdiction publishes for this application's path — `by_right_review_days` for `BY_RIGHT`, `conditional_use_review_days` for `CONDITIONAL_USE`, `variance_review_days` for `VARIANCE` — and further advanced by the application's accumulated `tolled_days`.

**Completeness and tolling.** The planner records a completeness determination through an `outcome` and an optional `note`. `COMPLETE` moves the application `SUBMITTED → UNDER_REVIEW`. `INCOMPLETE` is accepted from either `SUBMITTED` or `UNDER_REVIEW`, moves the application to `INCOMPLETE`, and stamps `incomplete_since_date` with the logical clock — the origin from which tolling accrues. `CURED` is accepted only from `INCOMPLETE`, requires `incomplete_since_date` to be set, and moves the application `INCOMPLETE → UNDER_REVIEW`; it adds to `tolled_days` the whole UTC days elapsed from `incomplete_since_date` to the logical clock, discarding any partial day and never contributing fewer than zero days, recomputes `shot_clock_deadline_date` with the new total, and clears `incomplete_since_date` back to null. The `INCOMPLETE → UNDER_REVIEW → INCOMPLETE` loop is repeatable, and each cure adds its own days to the running total, in cure order. An outcome the current status does not admit yields `ERR_INVALID_ZONING_STATE`.

**Hearings.** Hearing activity is driven by an `action` and, for two of the three, a `hearing_date`. `SCHEDULE` books a hearing and is accepted from `UNDER_REVIEW` or from `HEARING_HELD`, storing the supplied `hearing_date` and moving the application to `HEARING_SCHEDULED`; it does not touch `continuance_count`. `HOLD` records that the hearing actually took place, is accepted only from `HEARING_SCHEDULED`, requires the logical clock to have reached or passed the stored `hearing_date` — an earlier attempt yields `ERR_HEARING_NOT_YET_HELD` — and moves the application `HEARING_SCHEDULED → HEARING_HELD` while incrementing `hearings_held_count` by one. `CONTINUE` postpones a held hearing to a new date, is accepted only from `HEARING_HELD`, requires that `continuance_count` is still strictly below the jurisdiction's `max_continuances` — otherwise `ERR_CONTINUANCE_LIMIT_REACHED` — increments `continuance_count` by one, stores the new `hearing_date`, and moves the application `HEARING_HELD → HEARING_SCHEDULED`. Each granted continuance also inflates the schedule risk of the ring's on-air plan, which picks the new `continuance_count` up on its next forecast.

Both `SCHEDULE` and `CONTINUE` are subject to two date rules. The requested `hearing_date` must be at or after the current logical clock; an earlier date yields `ERR_HEARING_DATE_IN_PAST` (422). And the jurisdiction's calendar must have room: no *other* zoning application in the same jurisdiction may hold a `hearing_date` — whatever that other application's own status, terminal statuses included — strictly within the jurisdiction's `hearing_cadence_days` whole days of the requested date. A separation exactly equal to `hearing_cadence_days` is allowed; anything closer yields `ERR_HEARING_WINDOW_CONFLICT`.

**Decisions.** A decision is recorded with an `outcome` of `APPROVED` or `DENIED` together with a `decision_date`. The ordinary path is from `HEARING_HELD`, and both outcomes are available there. From `UNDER_REVIEW` the paths are deliberately asymmetric: a `DENIED` outcome may be recorded from `UNDER_REVIEW` for an application of any `application_type`, whereas an `APPROVED` outcome may be recorded from `UNDER_REVIEW` only when `application_type` is `BY_RIGHT`, since a by-right filing needs no public hearing to be granted. An approval from `UNDER_REVIEW` on a `CONDITIONAL_USE` or `VARIANCE` application is therefore refused with `ERR_INVALID_ZONING_STATE`, as is any decision from a status outside `HEARING_HELD` and `UNDER_REVIEW`. The supplied `decision_date` must not be after the logical clock, otherwise `ERR_DATE_IN_FUTURE` (422), and must be at or after `submitted_date`, otherwise `ERR_DECISION_DATE_INVALID` (422) — evaluated in that order, per the precedence of §2.9, so a future date that also precedes submission reports `ERR_DATE_IN_FUTURE`. On success the date is stored, the status becomes `APPROVED` or `DENIED`, and an `APPROVED` outcome promotes the candidate `STRUCTURALLY_CLEARED → ENTITLED` when the candidate is in `STRUCTURALLY_CLEARED`.

**Deemed granted.** When a jurisdiction lets the federal shot clock run out, a `ProgramDirector` declares the application granted by operation of law. This is accepted from `SUBMITTED`, `UNDER_REVIEW`, `INCOMPLETE`, `HEARING_SCHEDULED` or `HEARING_HELD`, and requires the logical clock to be **strictly after** `shot_clock_deadline_date`; a clock resting exactly on the deadline has not yet run out, and the attempt is refused with `ERR_SHOT_CLOCK_NOT_EXPIRED`. On success `decision_date` is stamped with the logical clock, the status becomes `DEEMED_GRANTED`, and the candidate is promoted `STRUCTURALLY_CLEARED → ENTITLED` when it is in `STRUCTURALLY_CLEARED`. `APPROVED`, `DENIED`, `DEEMED_GRANTED` and `WITHDRAWN` are all terminal; an application in any non-terminal status is set to `WITHDRAWN` when its candidate becomes `DISQUALIFIED` or `RELINQUISHED`, and that withdrawal cancels the candidate's `REQUESTED` and `SCHEDULED` backhaul orders.

A computed read exposes the shot-clock position to the planner and the program authority. It reports `review_days`, the nominal review-day count the jurisdiction publishes for this application's `application_type`; `tolled_days`, the accumulated tolling; `shot_clock_deadline_date` as stored; `days_remaining`, the whole days from the current logical clock to that deadline, which goes negative once the deadline has passed; and `deemed_grantable`, true exactly when the logical clock is strictly after `shot_clock_deadline_date`. On an application still in `PREPARING`, where no deadline has yet been stamped, `shot_clock_deadline_date` and `days_remaining` are both null and `deemed_grantable` is false.

### 3.7. Environmental and Historic Review with Tribal Consultation

An `EnvironmentalReviewer` opens the environmental record for a candidate by naming it through `candidate_id`, declaring the NEPA screening class through `nepa_category` — `CATEGORICAL_EXCLUSION` or `ENVIRONMENTAL_ASSESSMENT` — and flagging through `section106_required` whether the Section 106 historic-properties review applies. A candidate may carry only one live review: if it already has a review whose status is anything other than `ADVERSE_EFFECT`, the creation is refused with `ERR_DUPLICATE_ENVIRONMENTAL_REVIEW`. A new review begins with `status` at `NOT_STARTED`, both branch dimensions — `public_notice_branch_status` and `tribal_branch_status` — at `NOT_STARTED`, and `tcns_notice_date` and `tribal_response_deadline_date` null.

At creation the server determines **tribal-consultation scope** and writes it to `tribal_consultation_required`. It is true when the candidate's jurisdiction has `tribal_consultation_required` set to true, or when the candidate's landlord has `entity_type` equal to `TRIBAL_AUTHORITY`; either condition alone suffices, and it is false only when neither holds.

**The fork.** Screening moves the review `NOT_STARTED → SCREENING` and is accepted only from `NOT_STARTED`; screening a review that has already been screened is refused with `ERR_INVALID_REVIEW_STATE`. Screening always sets `public_notice_branch_status` to `PENDING`. The tribal branch depends on scope: when `tribal_consultation_required` is true, `tribal_branch_status` becomes `PENDING`, `tcns_notice_date` is stamped with the logical clock as the moment the TCNS notice went out, and `tribal_response_deadline_date` is set to thirty days after `tcns_notice_date`; when `tribal_consultation_required` is false, `tribal_branch_status` becomes `NOT_APPLICABLE` and both dates stay null.

**The join.** Branches are closed one at a time, each closure naming a `branch` — `PUBLIC_NOTICE` or `TRIBAL` — and carrying a `finding` of `NO_ADVERSE_EFFECT` or `ADVERSE_EFFECT`. The named branch must be `PENDING`; closing a branch that is already `COMPLETE`, or one that is `NOT_APPLICABLE`, is refused with `ERR_INVALID_REVIEW_STATE`. Closing the `TRIBAL` branch additionally requires that the logical clock has reached or passed `tribal_response_deadline_date` — the tribes get their full window. Equality closes the branch; one second earlier does not, and the attempt is refused with `ERR_TRIBAL_RESPONSE_WINDOW_OPEN`. Every closure sets the named branch's status to `COMPLETE` and increments the review's `version`.

Where the closure leaves the review depends on what remains. With a `NO_ADVERSE_EFFECT` finding, closing one branch while the other is still `PENDING` moves the review `SCREENING → IN_CONSULTATION`. Closing the last `PENDING` branch — the point at which `public_notice_branch_status` is `COMPLETE` and `tribal_branch_status` is either `COMPLETE` or `NOT_APPLICABLE` — moves the review to `CLEARED` and sets the candidate's `environmental_cleared` to true; this join fires from `IN_CONSULTATION` in the two-branch case, and directly from `SCREENING` when the tribal branch was `NOT_APPLICABLE` and the public-notice branch is the only one to close.

An `ADVERSE_EFFECT` finding on **either** branch short-circuits the join. Whether the review sits in `SCREENING` or in `IN_CONSULTATION`, and whether the branch closed is `PUBLIC_NOTICE` or `TRIBAL`, the named branch is marked `COMPLETE`, the review moves to `ADVERSE_EFFECT`, and the candidate's `environmental_cleared` is set to false. The tribal-window requirement still applies to a `TRIBAL` branch carrying an adverse finding. `CLEARED` and `ADVERSE_EFFECT` are both terminal — which is why an `ADVERSE_EFFECT` review does not block a fresh review from being opened on the same candidate, while a `CLEARED` one does.

Downstream, `environmental_cleared` is a hard prerequisite in exactly two places: a candidate cannot be marked build-ready and a construction permit cannot be issued unless it is true, and either attempt otherwise yields `ERR_ENVIRONMENTAL_NOT_CLEARED`.

### 3.8. Construction Permitting and Backhaul Crew Coordination

A `ConstructionManager` files a construction permit application for a candidate through `candidate_id`, a `permit_type` of `BUILDING`, `ELECTRICAL` or `ROW`, and an optional `valid_days` validity window — an integer of at least 1 — that defaults to 180 days. Filing is admitted whatever the candidate's two dimensions read; the entitlement and environmental gates belong to issuance, not to filing. The permit begins in `SUBMITTED` with `submitted_date` stamped from the logical clock and `issued_date`, `expiry_date` and `revocation_reason` null.

Issuance moves the permit `SUBMITTED → ISSUED` and carries an `issued_date` that must not be after the logical clock, on pain of `ERR_DATE_IN_FUTURE`. It requires the candidate's `feasibility_status` to be `ENTITLED` or `BUILD_READY` — the zoning entitlement must already be in hand, and a candidate that has not reached one of those two states yields `ERR_ZONING_NOT_APPROVED` — and it requires `environmental_cleared` to be true, that environmental check being the one evaluated first per the precedence of §2.9. On success the supplied `issued_date` is stored, `expiry_date` is set to `issued_date` advanced by `valid_days` days, and the candidate's `permit_issued` becomes true. Issuing a permit that is not `SUBMITTED`, or revoking one that is not `ISSUED`, is refused with `ERR_INVALID_PERMIT_STATE`.

A permit leaves `ISSUED` in two ways, and both have the same downstream consequences. Revocation is deliberate: the manager supplies a `revocation_reason`, which is stored, and the permit moves `ISSUED → REVOKED`. Expiry is automatic but **lazy**: the permit is evaluated whenever it is read or relied upon, and if the logical clock has moved strictly past `expiry_date` the permit moves `ISSUED → EXPIRED` at that moment. The occasions that evaluate it are exactly these: reading it singly; reading the permit collection, which sweeps every stored permit before filters and paging are applied; issuing or revoking it; site selection, which sweeps the permits of every candidate on the ring; on-air forecasting and activation, which sweep the driver's and the selected candidate's permits; and marking a candidate build-ready. The transition and all of its downstream effects fire even when the request that triggered the evaluation then fails — a `mark-build-ready` refused with `ERR_PERMIT_EXPIRED` still leaves the permit `EXPIRED` and the candidate's `permit_issued` false. In either case the candidate's `permit_issued` is set back to false, a candidate sitting in `BUILD_READY` is reverted `BUILD_READY → ENTITLED`, and if that candidate was the ring's `selected_candidate_id`, the ring's selection is cleared to null and the ring returns to `OPEN`. `EXPIRED` and `REVOKED` are both terminal.

**Marking a candidate build-ready** is the `ConstructionManager`'s declaration that everything is in place, and it is the narrowest gate in the system. The state gate admits a candidate whose `feasibility_status` is `STRUCTURALLY_CLEARED` or `ENTITLED` and whose `acquisition_status` is `LEASE_EXECUTED`; anything else yields `ERR_INVALID_CANDIDATE_STATE`. Past that gate, three prerequisites are checked in order: `environmental_cleared` must be true, or `ERR_ENVIRONMENTAL_NOT_CLEARED`; `permit_issued` must be true and the candidate must actually have a permit in `ISSUED` status, or `ERR_PERMIT_NOT_ISSUED`; and that issued permit must not have passed its `expiry_date` at the current logical clock, or `ERR_PERMIT_EXPIRED`. In practice only an `ENTITLED` candidate can satisfy all three, because permit issuance itself requires entitlement — the wider state gate exists so that the environmental and permit checks are reachable and report their own diagnostics rather than being masked by a state error. On success the candidate moves to `BUILD_READY` from whichever of the two admitted feasibility states it actually holds.

**Backhaul orders.** Power and fiber are ordered per candidate against a registered provider: `candidate_id` names the site, `provider_id` the provider, `order_type` declares `POWER` or `FIBER`, and `window_start` and `window_end` bound the crew window. The window is **half-open**: `window_start` is inclusive, `window_end` is exclusive, and `window_end` must be strictly after `window_start`. The order's `crew_days` is the whole UTC days spanned by that half-open window, discarding any partial day; a window that spans fewer than one whole day yields `ERR_INVALID_WINDOW` (422). A new order begins in `REQUESTED` with `delivered_date` null.

Creating an order is also gated on the provider's crew capacity, day by day. For every UTC day covered by the new half-open window — a day counting as covered when its `00:00:00Z` boundary falls at or after `window_start` and strictly before `window_end`, so that a partial leading day is not covered — the server counts the provider's existing orders in `REQUESTED` or `SCHEDULED` status whose own half-open window covers that day under the same test; adding one for the order being created, the result must not exceed the provider's `concurrent_crew_capacity` on any single day. If it would, the order is refused with `ERR_PROVIDER_CAPACITY_EXCEEDED`. Because the interval is half-open, an order whose `window_start` falls exactly on another order's `window_end` shares no day with it and never conflicts.

A provider's `committed_crew_days` is the sum of `crew_days` across that provider's orders whose status is `REQUESTED` or `SCHEDULED`; `DELIVERED` and `CANCELLED` orders are excluded both from that sum and from the day-coverage count. The figure is recomputed after every order creation and after every status action, so it always equals that sum exactly.

Status actions are driven by an `action` and, for one of them, a `delivered_date`. `SCHEDULE` moves the order `REQUESTED → SCHEDULED`. `CANCEL` is accepted from either `REQUESTED` or `SCHEDULED` and moves the order to `CANCELLED` from either. `DELIVER` is accepted only from `SCHEDULED`, requires `delivered_date` to be present and not after the logical clock — a future date yields `ERR_DATE_IN_FUTURE` — stores it, and moves the order `SCHEDULED → DELIVERED`. Each action recomputes the provider's `committed_crew_days`. An action the current status does not admit yields `ERR_INVALID_ORDER_STATE`. Orders in `REQUESTED` or `SCHEDULED` are additionally cancelled without any client request when a zoning application of the same candidate is withdrawn. `DELIVERED` and `CANCELLED` are both terminal.

### 3.9. Site Selection, Schedule Forecasting and Going On Air

**Selecting the winner.** With one or more candidates fully developed, a `ProgramDirector` picks the site the program will build. Selection requires the ring to be `OPEN`, requires the `expected_search_ring_version` guard of §2.7, and requires at least one candidate of that ring to be simultaneously `LEASE_EXECUTED` on the acquisition dimension and `BUILD_READY` on the feasibility dimension. Exactly those candidates form the eligible pool; `RELINQUISHED` and `DISQUALIFIED` candidates are excluded, as is any candidate that has not reached both states. If the pool is empty, no candidate is selected, the ring stays `OPEN`, and the request is refused with `ERR_NO_ELIGIBLE_CANDIDATE`.

Within the pool the winner is chosen by a three-step ordering, evaluated on stored two-decimal values with exact comparison and never involving record identifiers. Candidates are ranked by `rf_qualification_score` from highest to lowest. Ties on score are broken by the `committed_rent_final_usd` of the candidate's `EXECUTED` lease, cheapest total rent first. Ties that survive both are broken by the candidate's `created_at`, earliest first. The winner is written to the ring's `selected_candidate_id`, the ring moves `OPEN → SITE_SELECTED`, and `committed_capex_usd` is recomputed.

A selection can come undone in three ways. The `ProgramDirector` may reopen the ring deliberately, as described in §3.1. Or the selected candidate may leave the eligible pool on its own — becoming `RELINQUISHED` on the acquisition dimension or `DISQUALIFIED` on the feasibility dimension — in which case `selected_candidate_id` is cleared to null, the ring returns `SITE_SELECTED → OPEN`, and both `candidate_count` and `committed_capex_usd` are recomputed. Or the selected candidate may fall out of `BUILD_READY` when its issued permit is revoked or expires, which likewise clears the selection and returns the ring to `OPEN`.

**The on-air plan.** A `ProgramDirector` creates the milestone plan for a ring by naming it through `search_ring_id` and committing to a `target_on_air_date`. The ring may be in any `status` at that moment, the target may fall anywhere on the timeline — before the logical clock as readily as after it — and nothing prevents a ring from carrying several plans at once. The plan begins in `PLANNED` with `reset_count` at 0, `actual_on_air_date` null and `variance_days` null, and both forecast variants are computed immediately, so a plan whose very first forecast bands `HIGH` is still created in `PLANNED` and only re-bands on its next reforecast. Forecasts are recomputed on demand through a reforecast, on every reset of the target, and are also available as a computed read that recomputes at the current logical clock without mutating the plan.

Forecasting begins by resolving the **driver candidate** — the candidate whose remaining work sets the date. If the ring already has a `selected_candidate_id`, that candidate is the driver. Otherwise the driver is chosen from the ring's candidates whose `acquisition_status` is not `RELINQUISHED` and whose `feasibility_status` is not `DISQUALIFIED`, ranked by `rf_qualification_score` from highest to lowest with candidates whose score is still null ranking last, ties broken by `created_at` earliest first. If that pool is empty there is nothing to forecast and the request is refused with `ERR_NO_ELIGIBLE_CANDIDATE` — without exception on plan creation and on reforecast, both of which insist on a freshly resolvable driver even when the plan already names one. A reset and the computed forecast read are gentler: on an empty pool they fall back to the `driver_candidate_id` the plan already records, and reach `ERR_NO_ELIGIBLE_CANDIDATE` only when there is no such recorded driver to reuse. The resolved driver is recorded on the plan as `driver_candidate_id`.

**Remaining work** is then assembled from five terms, summed in this fixed order:

- *Structural*: twenty-one days when the driver's `feasibility_status` is `UNSCREENED`, `RF_QUALIFIED` or `STRUCTURAL_HOLD`, and nothing otherwise.
- *Environmental*: thirty days when the driver's `environmental_cleared` is false, and nothing when it is true.
- *Zoning*: the driver's zoning application is the one whose status is neither `WITHDRAWN` nor `DENIED`, and at most one such application can exist. If that application exists and its status is `APPROVED` or `DEEMED_GRANTED`, this term is nothing. If it exists in any other status, the term is the jurisdiction's nominal review days for that application's `application_type`. If the driver has no such application at all, the term is the jurisdiction's `conditional_use_review_days`, the middle path being the planning assumption.
- *Permit*: twenty-five days when the driver's `permit_issued` is false, and nothing when it is true.
- *Backhaul*: nothing when the driver has at least one `DELIVERED` order of `order_type` `POWER` and at least one `DELIVERED` order of `order_type` `FIBER`. Otherwise, if the driver has no backhaul order at all, forty-five days. Otherwise, the whole days from the current logical clock to the latest `window_end` among the driver's orders whose status is `REQUESTED` or `SCHEDULED`, floored at zero so that a window already in the past contributes nothing; if the driver has orders but none in those two statuses, this term is zero.

The continuance count used by the forecast is the `continuance_count` of that same zoning application, or zero when no such application exists.

The **baseline** variant is simply the current logical clock advanced by the total remaining days — nominal durations, no delay factor, no continuance penalty — and is stored as `baseline_forecast_date`. The **risk-adjusted** variant inflates the work: the remaining days are multiplied by the jurisdiction's `historical_delay_factor` and rounded *up* to a whole number of days, and to that is added the continuance count multiplied by the jurisdiction's `hearing_cadence_days`, so each continuance the authority granted costs one full hearing cycle. The current logical clock advanced by that inflated day count is stored as `risk_adjusted_forecast_date`.

The slip is the whole days from the plan's `target_on_air_date` to `risk_adjusted_forecast_date`, and is negative when the risk-adjusted forecast lands early. `schedule_risk_score` starts from a baseline of 50, adds 2.0 points for each day of slip (which subtracts when the slip is negative), adds 5 points for each continuance, and adds a further 10 points when the driver's `feasibility_status` is `STRUCTURAL_HOLD`, since a structure awaiting modification is the least predictable state in the pipeline. The result is clamped to the range 0 through 100 and then rounded half up to two decimal places. `risk_band` bands that score: `HIGH` at 70.00 or above, `MEDIUM` at 40.00 or above but below 70.00, and `LOW` below 40.00.

**Plan status.** Reforecasting is accepted while the plan is `PLANNED`, `AT_RISK` or `RESET`, recomputes `baseline_forecast_date`, `risk_adjusted_forecast_date`, `schedule_risk_score`, `risk_band` and `driver_candidate_id`, and then sets the status from the new band: a `HIGH` band puts the plan in `AT_RISK`, and any other band puts it in `PLANNED`. So a `PLANNED` plan that reforecasts to `HIGH` moves `PLANNED → AT_RISK`; an `AT_RISK` plan that reforecasts to `LOW` or `MEDIUM` moves `AT_RISK → PLANNED`; a `RESET` plan moves `RESET → PLANNED` when the new band is `LOW` or `MEDIUM` and `RESET → AT_RISK` when it is `HIGH`, so a reset target that is still unreachable re-enters `AT_RISK` rather than stranding the plan in `RESET`.

Resetting the committed date is accepted while the plan is `PLANNED` or `AT_RISK`, and carries a `new_target_on_air_date` together with a `reason`. The new date must be strictly after the current logical clock; a date at or before the clock is refused with `ERR_TARGET_DATE_IN_PAST` (422). On success `target_on_air_date` is replaced with `new_target_on_air_date`, `reset_count` increments by one, the forecast fields are recomputed and the plan moves to `RESET`. A plan already in `RESET` must be reforecast back to `PLANNED` or `AT_RISK` before it can be reset again. Any of these actions attempted on a plan whose status does not admit it is refused with `ERR_INVALID_PLAN_STATE`.

**Going on air.** Activation is the `ConstructionManager`'s final act and is accepted from `PLANNED`, `AT_RISK` or `RESET` — identical preconditions and identical effects from all three. The ring must be in `SITE_SELECTED`; the ring's selected candidate must have `feasibility_status` equal to `BUILD_READY`, or `ERR_CANDIDATE_NOT_BUILD_READY`; that candidate must have at least one `DELIVERED` backhaul order of `order_type` `POWER` and at least one of `order_type` `FIBER`, or `ERR_BACKHAUL_NOT_DELIVERED`; and the supplied `actual_on_air_date` must not be after the logical clock, or `ERR_DATE_IN_FUTURE`. On success `actual_on_air_date` is stored, `variance_days` is set to the whole days from `target_on_air_date` to `actual_on_air_date` — negative when the site went live early — the plan moves to the terminal `ON_AIR`, and the ring moves `SITE_SELECTED → ON_AIR`, its own terminal state.

A computed read exposes the forecast to the program authority and the construction manager without mutating the plan. It reports `baseline_forecast_date` and `risk_adjusted_forecast_date` as recomputed at the current logical clock, `remaining_days` as the nominal total, `risk_days` as the inflated total including continuance penalties, `schedule_risk_score`, `risk_band`, `slip_days`, and `driver_candidate_id`.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`; every other successful operation, including all state transitions, action endpoints and computed reads, returns `200 OK`. All paths are mounted at the service root. Request payloads, response payloads and side effects are not repeated here — they are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | ProgramDirector |
| POST | `/search-rings` | Create an RF search ring in `DRAFT` | RfEngineer |
| GET | `/search-rings` | List search rings | Any role |
| GET | `/search-rings/{id}` | Read one search ring, including its `version` | Any role |
| POST | `/search-rings/{id}/open` | Open a `DRAFT` ring for candidate development | RfEngineer |
| POST | `/search-rings/{id}/select-site` | Select the winning candidate for an `OPEN` ring | ProgramDirector |
| POST | `/search-rings/{id}/reopen` | Undo a site selection and return the ring to `OPEN` | ProgramDirector |
| POST | `/landlords` | Register a landlord | SiteAcquisitionAgent |
| GET | `/landlords/{id}` | Read one landlord | Any role |
| POST | `/landlords/{id}/standing` | Set a landlord's commercial standing | ProgramDirector |
| POST | `/jurisdictions` | Register a zoning jurisdiction and its review calendar | ZoningPlanner |
| GET | `/jurisdictions/{id}` | Read one jurisdiction | Any role |
| POST | `/candidates` | Add a candidate site to a ring | SiteAcquisitionAgent |
| GET | `/candidates` | List candidates | Any role |
| GET | `/candidates/{id}` | Read one candidate, including its `version` | Any role |
| PATCH | `/candidates/{id}` | Update the RF survey inputs of an unscreened candidate | SiteAcquisitionAgent |
| POST | `/candidates/{id}/outreach-events` | Record a landlord outreach event | SiteAcquisitionAgent |
| POST | `/candidates/{id}/rf-qualify` | Score the candidate against the ring's RF objectives | RfEngineer |
| POST | `/candidates/{id}/mark-build-ready` | Declare the candidate construction-ready | ConstructionManager |
| POST | `/leases` | Draft a ground lease for a candidate | SiteAcquisitionAgent |
| GET | `/leases` | List leases | Any role |
| GET | `/leases/{id}` | Read one lease | Any role |
| POST | `/leases/{id}/rounds` | Record a negotiation round or accept the current terms | SiteAcquisitionAgent |
| POST | `/leases/{id}/execute` | Execute an accepted lease | ProgramDirector |
| POST | `/leases/{id}/terminate` | Terminate an executed lease | ProgramDirector |
| GET | `/leases/{id}/rent-schedule` | Computed read: both committed-rent variants and their delta | SiteAcquisitionAgent, ProgramDirector |
| POST | `/zoning-applications` | Prepare a zoning application for a candidate | ZoningPlanner |
| GET | `/zoning-applications` | List zoning applications | Any role |
| GET | `/zoning-applications/{id}` | Read one zoning application | Any role |
| POST | `/zoning-applications/{id}/visual-simulations` | Attach a photo simulation to a `PREPARING` application | ZoningPlanner |
| POST | `/zoning-applications/{id}/submit` | File the application and start the shot clock | ZoningPlanner |
| POST | `/zoning-applications/{id}/completeness` | Record a completeness determination or cure a filing | ZoningPlanner |
| POST | `/zoning-applications/{id}/hearings` | Schedule, hold or continue the public hearing | ZoningPlanner |
| POST | `/zoning-applications/{id}/decide` | Record the authority's decision | ZoningPlanner |
| POST | `/zoning-applications/{id}/deem-granted` | Declare the application granted once the shot clock has run | ProgramDirector |
| GET | `/zoning-applications/{id}/shot-clock` | Computed read: shot-clock position and tolling | ZoningPlanner, ProgramDirector |
| POST | `/structural-analyses` | Open a TIA-222 loading analysis for a candidate | StructuralEngineer |
| GET | `/structural-analyses` | List structural analyses | Any role |
| GET | `/structural-analyses/{id}` | Read one structural analysis | Any role |
| POST | `/structural-analyses/{id}/complete` | Complete the analysis and classify the result | StructuralEngineer |
| POST | `/modification-designs` | Create a modification design against a completed analysis | StructuralEngineer |
| GET | `/modification-designs` | List modification designs | Any role |
| GET | `/modification-designs/{id}` | Read one modification design | Any role |
| POST | `/modification-designs/{id}/peer-review` | Drive the peer-review cycle | StructuralEngineer |
| POST | `/environmental-reviews` | Open the NEPA and Section 106 review for a candidate | EnvironmentalReviewer |
| GET | `/environmental-reviews` | List environmental reviews | Any role |
| GET | `/environmental-reviews/{id}` | Read one environmental review | Any role |
| POST | `/environmental-reviews/{id}/screen` | Fork the review into its public-notice and tribal branches | EnvironmentalReviewer |
| POST | `/environmental-reviews/{id}/branch-complete` | Close one review branch with a finding | EnvironmentalReviewer |
| POST | `/construction-permits` | File a construction permit application | ConstructionManager |
| GET | `/construction-permits` | List construction permits | Any role |
| GET | `/construction-permits/{id}` | Read one construction permit | Any role |
| POST | `/construction-permits/{id}/issue` | Issue the permit | ConstructionManager |
| POST | `/construction-permits/{id}/revoke` | Revoke an issued permit | ConstructionManager |
| POST | `/utility-providers` | Register a power or fiber provider | ConstructionManager |
| GET | `/utility-providers/{id}` | Read one utility provider | Any role |
| POST | `/backhaul-orders` | Request a power or fiber crew window | ConstructionManager |
| GET | `/backhaul-orders` | List backhaul orders | Any role |
| GET | `/backhaul-orders/{id}` | Read one backhaul order | Any role |
| POST | `/backhaul-orders/{id}/status-actions` | Schedule, cancel or record delivery of a crew window | ConstructionManager |
| POST | `/on-air-plans` | Create the on-air milestone plan for a ring | ProgramDirector |
| GET | `/on-air-plans` | List on-air plans | Any role |
| GET | `/on-air-plans/{id}` | Read one on-air plan | Any role |
| POST | `/on-air-plans/{id}/reforecast` | Re-run both forecast variants and re-band the plan | ProgramDirector |
| POST | `/on-air-plans/{id}/reset` | Reset the committed on-air target date | ProgramDirector |
| POST | `/on-air-plans/{id}/activate` | Record the site as on air | ConstructionManager |
| GET | `/on-air-plans/{id}/forecast` | Computed read: both forecast variants and the risk score | ProgramDirector, ConstructionManager |

"Any role" means all seven roles listed in §2.1.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_CANDIDATE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_SEARCH_RING_NOT_FOUND` | 404 |
| `ERR_CANDIDATE_NOT_FOUND` | 404 |
| `ERR_LANDLORD_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_ZONING_APPLICATION_NOT_FOUND` | 404 |
| `ERR_STRUCTURAL_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_MODIFICATION_DESIGN_NOT_FOUND` | 404 |
| `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_UTILITY_PROVIDER_NOT_FOUND` | 404 |
| `ERR_BACKHAUL_ORDER_NOT_FOUND` | 404 |
| `ERR_ON_AIR_PLAN_NOT_FOUND` | 404 |
| `ERR_STALE_CANDIDATE_VERSION` | 412 |
| `ERR_STALE_RING_VERSION` | 412 |
| `ERR_RING_NOT_OPEN` | 409 |
| `ERR_INVALID_RING_STATE` | 409 |
| `ERR_INVALID_CANDIDATE_STATE` | 409 |
| `ERR_INVALID_LEASE_STATE` | 409 |
| `ERR_INVALID_ZONING_STATE` | 409 |
| `ERR_ANALYSIS_SUPERSEDED` | 409 |
| `ERR_INVALID_ANALYSIS_STATE` | 409 |
| `ERR_INVALID_DESIGN_STATE` | 409 |
| `ERR_INVALID_REVIEW_STATE` | 409 |
| `ERR_INVALID_PERMIT_STATE` | 409 |
| `ERR_INVALID_ORDER_STATE` | 409 |
| `ERR_INVALID_PLAN_STATE` | 409 |
| `ERR_MARKET_MISMATCH` | 409 |
| `ERR_LANDLORD_MISMATCH` | 409 |
| `ERR_LANDLORD_OPTED_OUT` | 409 |
| `ERR_LANDLORD_NOT_IN_GOOD_STANDING` | 409 |
| `ERR_ENVIRONMENTAL_NOT_CLEARED` | 409 |
| `ERR_TRIBAL_RESPONSE_WINDOW_OPEN` | 409 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_PERMIT_EXPIRED` | 409 |
| `ERR_ZONING_NOT_APPROVED` | 409 |
| `ERR_LEASE_NOT_EXECUTED` | 409 |
| `ERR_CANDIDATE_NOT_BUILD_READY` | 409 |
| `ERR_BACKHAUL_NOT_DELIVERED` | 409 |
| `ERR_VISUAL_SIMULATION_REQUIRED` | 422 |
| `ERR_CONTINUANCE_LIMIT_REACHED` | 409 |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 409 |
| `ERR_DUPLICATE_ZONING_APPLICATION` | 409 |
| `ERR_DUPLICATE_ENVIRONMENTAL_REVIEW` | 409 |
| `ERR_NO_ELIGIBLE_CANDIDATE` | 409 |
| `ERR_HEARING_WINDOW_CONFLICT` | 409 |
| `ERR_PROVIDER_CAPACITY_EXCEEDED` | 409 |
| `ERR_SHOT_CLOCK_NOT_EXPIRED` | 409 |
| `ERR_HEARING_DATE_IN_PAST` | 422 |
| `ERR_HEARING_NOT_YET_HELD` | 409 |
| `ERR_DATE_IN_FUTURE` | 422 |
| `ERR_DECISION_DATE_INVALID` | 422 |
| `ERR_TARGET_DATE_IN_PAST` | 422 |
| `ERR_CAPEX_BUDGET_EXCEEDED` | 409 |
| `ERR_RENT_VARIANCE_EXCEEDED` | 409 |

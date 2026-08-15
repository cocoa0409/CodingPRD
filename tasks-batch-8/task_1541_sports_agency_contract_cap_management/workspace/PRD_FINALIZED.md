# Sports Agency Contract & Cap Management API — Product Requirements Document

## 1. Introduction

A certified player agency lives at the intersection of two balance sheets: the player's earning power and the club's salary cap. Every representation decision — whether to hold out for a richer guarantee, when to exercise a qualifying offer, how to structure a signing bonus against an escalating base — is made in the shadow of a hard cap, a luxury-tax threshold, and a league certification regime that caps the fees an agent may lawfully earn. Negotiations are not single events but numbered rounds of proposals and counters, each of which reserves real cap space the moment it hits the market; disputes spill into grievances that can end in arbitration; and when a player changes representation mid-contract, the commission on the remaining years has to be split between the departing and the incoming agent down to the cent.

This document specifies the Sports Agency Contract & Cap Management API, the system of record for that entire book of business. It governs agency and agent onboarding under certification rules, client roster management including mid-contract representation transitions and releases, cap-season accounting with committed and reserved space, proposal-driven negotiation between agents and team front offices, contract signing and cap posting, endorsement income held strictly apart from playing contracts, tender and option exercise windows, grievance adjudication, and the agency fee ledger in which every earned commission is accrued, split, paid, or voided. All monetary quantities are integer cents, and all temporal reasoning runs against a deterministic logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request whose headers are missing or malformed, or whose role is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (401). The declared roles are `LeagueOfficer`, `AgencyManager`, `Agent`, `Team`, and `Player`. When the role is recognized but is not among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN` (403).

- A `LeagueOfficer` is the league operations role: it creates agencies and teams, administers cap seasons, and adjudicates grievances. When `X-User-Role` is `LeagueOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- An `AgencyManager` is a manager within an agency — an agent holding the manager flag — who certifies agents, drives client transitions, approves and terminates endorsements, voids contracts, and marks fees paid. When `X-User-Role` is `AgencyManager`, `X-User-ID` is the `id` of the acting Agent; ownership checks on any resource that references an Agent compare the resource's foreign-key field to `X-User-ID`.
- An `Agent` is a certified player agent who files proposals, signs contracts, exercises options, files grievances, and creates endorsement deals. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting Agent; ownership checks on resources that reference an Agent compare fields such as `proposed_by_agent_id`, `primary_agent_id`, or `filed_by_agent_id` to `X-User-ID`.
- A `Team` principal represents a club's front office and counters, accepts, or rejects proposals. When `X-User-Role` is `Team`, `X-User-ID` is the `id` of the acting Team; ownership checks on any resource that references a Team compare the resource's foreign-key field to `X-User-ID`.
- A `Player` is a read-only role for the athlete. When `X-User-Role` is `Player`, `X-User-ID` is the `id` of the acting Client; ownership checks on any resource that references a Client compare the resource's foreign-key field to `X-User-ID`.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many leading items and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in the system — Agency, Agent, Client, Team, CapSeason, Contract, Proposal, EndorsementDeal, TenderOption, Grievance, and FeeLedgerEntry — carries four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation. The `version` field is an integer that increments by one on every mutation. Mutations caused by cascading side effects — a cap season's counters moving because a proposal was submitted, a client sliding into transition because an agent's certification was revoked — count as mutations of the affected resource and therefore refresh its `updated_at` and increment its `version`.

### 2.5. The Logical Clock

All temporal reasoning runs against a server-maintained logical UTC clock. The server boots with its logical clock set to 2026-08-01T00:00:00Z and must never fall back to wall-clock time. A `LeagueOfficer` or `AgencyManager` may set the logical clock to a supplied `to_iso8601` instant through the clock-setting capability; the response reports the resulting `current_utc`. Automatic state changes — an endorsement deal completing when its `end_date` is reached, a tender option expiring once its `window_close_at` has passed — are evaluated against this logical clock, and so are all exercise-window checks. These automatic transitions are applied as the first step of processing every request, before that request's validation pipeline runs, so a record whose transition instant the clock has passed is already observed in its new state by the pipeline: an exercise attempt against a tender option whose `window_close_at` has passed fails the state check with `ERR_INVALID_STATE`, and the ownership and window checks are never reached for it.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents, carried in fields suffixed `_cents`; fractional cents exist nowhere in the system. Rates and percentages are exact decimal fractions: an agency `fee_cap_pct` of 0.03 means three percent, and a contract `escalator_pct` of 0.08 means an eight percent annual raise. Rate arithmetic is exact decimal arithmetic: a supplied rate is applied in calculations at its exact decimal value, with no binary floating-point approximation, so a product that lands exactly on a half-cent boundary — 300,002 × 0.25 = 75,000.5 cents — rounds up to the next whole cent, and range checks on rates, such as the §3.4 escalator ceiling, compare exactly and admit the 0.15 boundary value. Whenever a calculation produces a fractional cent, it is rounded half up to a whole cent. Multi-step calculations round at each per-season or per-ledger-entry step exactly where the governing rule in §3 specifies, and again at any final division step — never twice at the same step, never later than specified.

### 2.7. Request Validation Pipeline and Nested Resource Retrieval

Nested URLs are validated left to right. Each path identifier — agency, client, contract, proposal, and so on — must resolve within the scope established by the identifiers to its left; the request is rejected with `ERR_NOT_FOUND` (404) at the first identifier that does not resolve, before any later identifier is examined.

Beyond path resolution, every request passes a fixed validation pipeline, evaluated in order so that an earlier failure masks all later checks. First, authentication: the headers of §2.1 must be present and well formed, else `ERR_UNAUTHENTICATED` (401). Second, authorization: the acting role must appear in the endpoint's declared role list, else `ERR_FORBIDDEN` (403). Third, existence: the left-to-right path resolution above, else `ERR_NOT_FOUND` (404). Fourth, state: the target entity must be in the exact state the requested transition demands — a proposal must be in `DRAFT` to be submitted, a cap season in `OPEN` to be locked — else `ERR_INVALID_STATE` (409). Fifth, certification: actions league rules reserve for certified agents require the acting agent's `cert_status` to be `CERTIFIED`, else `ERR_AGENT_NOT_CERTIFIED` (422). Sixth, ownership: the acting agent must own the resource being acted upon, else `ERR_OWNERSHIP_VIOLATION` (422). Seventh, temporal windows: an option exercise must fall inside its declared window and an endorsement's date range must be coherent, else `ERR_WINDOW_CLOSED` (422). Eighth, the soft-cap reservation check on proposal submissions and resubmissions, else `ERR_CAP_WOULD_EXCEED` (422). Ninth, the hard-cap check on acceptance, else `ERR_CAP_HARD_LIMIT` (422). Tenth, resource locks: a cap season that is not `OPEN` blocks submissions, resubmissions, and acceptances, and a suspended agency blocks agent certification and endorsement approval, else `ERR_RESOURCE_LOCKED` (409). Eleventh, contract uniqueness, else `ERR_DUPLICATE_ACTIVE_CONTRACT` (409). Twelfth, field-level constraints on contract payloads, else `ERR_INVALID_REQUEST` (400). Thirteenth, the release gates on client obligations, else `ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS` (409). Fourteenth, the open-grievance gate on voiding a signed contract, else `ERR_OPEN_GRIEVANCE` (409). Because the soft-cap check at step eight outranks the resource-lock check at step ten, a submission that would both breach the luxury threshold and target a season that is not open surfaces `ERR_CAP_WOULD_EXCEED`, never `ERR_RESOURCE_LOCKED`.

### 2.8. The Salary-Cap Ledger: Committed and Reserved Space

Each cap season maintains two running counters. `committed_cents` is the sum of `aav_cents` across contracts signed into that season: it rises when a contract is signed and falls when a signed contract is voided. `reserved_cents` is the sum of `proposed_aav_cents` across proposals currently sitting in `SUBMITTED` or `COUNTERED` against contracts linked to that season; reservations are created by submission, adjusted by counters and resubmissions, and released by acceptance, rejection, withdrawal, and by the cascades described throughout §3 — agent suspension or revocation, season lock, contract signing or voiding. Both counters start at zero when the season is created.

Reading a cap season also returns two computed projections alongside its stored fields: `available_hard_cents`, the season's `cap_limit_cents` minus its `committed_cents` minus its `reserved_cents`, and `available_luxury_cents`, the season's `luxury_threshold_cents` minus committed minus reserved. A season in `LOCKED` accepts no new proposal activity; a season in `CLOSED` is terminal.

### 2.9. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, and no other endpoint takes a version field. Submitting a proposal requires the request to carry `expected_cap_season_version`, holding the cap season `version` the client last observed. If that value does not match the season's current `version` — because another proposal's submission, counter, acceptance, rejection, or withdrawal has already moved the season's reservation arithmetic since the client read it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never submits against capacity figures it has not observed. Signing a contract likewise requires `expected_contract_version`, holding the contract `version` the signer last observed; if that value does not match the contract's current `version` — for example because a proposal acceptance has already rewritten the contract's proposal set since the signer read it — the signing is rejected with `ERR_STALE_VERSION` (HTTP 412).

## 3. Business Logic & Workflows

### 3.1. Agency Onboarding and Agent Certification

A `LeagueOfficer` founds an agency by supplying its legal `name` and its `fee_cap_pct`, the maximum agent fee expressed as a fraction of a contract's average annual value — 0.03 for a three-percent cap — configured per agency within league limits. A new agency begins `ACTIVE`. Should the league suspend the agency, its `status` becomes `SUSPENDED`, which blocks all new proposals and endorsement activity under that agency's roof: certification attempts and endorsement approvals made while the agency is suspended are rejected with `ERR_RESOURCE_LOCKED`.

Once the agency exists, an `AgencyManager` registers agents with a `full_name`, a contact `email` that must be unique within the agency, the league-issued `cert_number`, and an optional `is_manager` flag — defaulting to false — that marks agents empowered to certify colleagues and resolve roster matters. The roster can be listed and filtered by `cert_status`. Every agent begins in `PENDING` certification. Certification, a manager's act that moves `cert_status` from `PENDING` to `CERTIFIED`, is permitted only while the agency itself is `ACTIVE`, and it stamps `certified_at` with the current UTC timestamp. Only `CERTIFIED` agents may submit or resubmit proposals, sign contracts, or exercise tender options; an attempt by anyone else is rejected with `ERR_AGENT_NOT_CERTIFIED`.

Certification can be interrupted and restored. Suspending a `CERTIFIED` agent moves them to `SUSPENDED` and immediately withdraws every proposal they authored that sits in `SUBMITTED` or `COUNTERED`, releasing the reserved cap space those proposals held on the linked cap season. Reinstating returns a `SUSPENDED` agent to `CERTIFIED` with no further side effects. Revocation is terminal: revoking a `CERTIFIED` agent moves every client whose `primary_agent_id` names that agent into `TRANSITIONING` with `transition_to_agent_id` left empty, and withdraws the agent's in-flight `SUBMITTED` or `COUNTERED` proposals with their reservations released; revoking a `SUSPENDED` agent likewise pushes that agent's clients into `TRANSITIONING`, the proposals having already been withdrawn at suspension time. A `REVOKED` agent never returns.

### 3.2. Client Roster: Registration, Representation Transitions, and Release

An `Agent` or `AgencyManager` registers a client by naming the `primary_agent_id` of the certified agent who will represent the player, together with the player's `full_name` and `position` — a label such as PG, WR, or ST. Clients begin `ACTIVE` and can be listed with filters on `status` and `primary_agent_id`.

Representation changes follow a two-step choreography. An `AgencyManager` initiates a transition by supplying `target_agent_id`, which must reference a `CERTIFIED` agent of the same agency; the client moves from `ACTIVE` to `TRANSITIONING` and `transition_to_agent_id` records the designated successor. Completion — again a manager's act — requires that the recorded successor still be `CERTIFIED`; it copies `transition_to_agent_id` into `primary_agent_id`, clears `transition_to_agent_id`, returns the client to `ACTIVE`, and settles the money between the outgoing and the incoming representative.

That settlement follows the transition-split rule. For every `SIGNED` contract on the transitioning client, the remaining term is the contract's `years` minus the number of seasons already elapsed, measured as the current season year minus the contract's `start_season_year`; the remaining value is the contract's `aav_cents` multiplied by that remaining term; and the remaining fee is that value multiplied by the agency's `fee_cap_pct`, rounded half up to a whole cent. Two fee ledger entries of kind `TRANSITION_ADJUSTMENT` are then written per signed contract: one crediting the outgoing agent with `split_pct` 0.25 — twenty-five percent of the remaining fee, rounded half up — and one crediting the incoming agent with `split_pct` 0.75. Because the two entries are rounded independently, any cent of rounding residue is assigned to the incoming agent, whose amount is computed as the remaining fee minus the outgoing agent's amount, so the pair always sums exactly to the remaining fee.

Release is the terminal roster act and is gated on obligations. From `ACTIVE`, a client may be released only when no contract for that client stands in `NEGOTIATING` or `SIGNED` and no endorsement deal is `ACTIVE`. From `TRANSITIONING`, the gate relaxes slightly: release is permitted once no `SIGNED` contract and no `ACTIVE` endorsement deal remain. Breaching either gate is rejected with `ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS`. A released client is `RELEASED` forever.

### 3.3. Teams and Cap-Season Administration

A `LeagueOfficer` registers each club with its `name` and its `league_code` — NBA, NFL, and the like. Against each team, the officer opens cap seasons by supplying the `season_year`, the `cap_limit_cents` for that season, and the `luxury_threshold_cents`, which must exceed the cap limit. A new cap season is `OPEN` with `committed_cents` and `reserved_cents` both zero, and seasons can be listed with filters on `status` or `season_year`.

Season administration has three moves. Locking moves a season from `OPEN` to `LOCKED` and force-withdraws every proposal in `SUBMITTED` or `COUNTERED` against contracts linked to that season, releasing their reserved space — the league's way of freezing a market. Unlocking returns a `LOCKED` season to `OPEN` with no further effects. Closing is terminal and is permitted from either `OPEN` or `LOCKED`, but only once `reserved_cents` has drained to zero; the season becomes `CLOSED`.

### 3.4. Contract Structure and Valuation

A contract takes shape when an `Agent` creates one under a client, naming the employing club via `team_id` and the season its average annual value will post against via `cap_season_id`, then describing the money: `start_season_year`; a term of `years` running between one and five seasons; the year-one `base_salary_cents`; the fully-guaranteed portion `guaranteed_cents`; and optionally a `signing_bonus_cents` and an `incentive_cents` pool, both defaulting to zero, plus an optional `escalator_pct` defaulting to zero. Three field constraints guard creation, and any later adjustment while the deal is still being negotiated: the term must run at least one season and no more than five; the guaranteed portion may not exceed the year-one base salary multiplied by the number of seasons; and the escalator must lie between zero and 0.15 inclusive. Violations are rejected with `ERR_INVALID_REQUEST`. Uniqueness is enforced per market as well: at most one contract in `NEGOTIATING` or `SIGNED` may exist for a given client-and-team pair, and a conflicting creation is rejected with `ERR_DUPLICATE_ACTIVE_CONTRACT`. A contract's life is tracked on two independent dimensions from birth — `signing_status` begins `NEGOTIATING` while `cap_posting_status` begins `UNPOSTED` — and contracts can be listed with filters on `signing_status` and `team_id`.

Valuation is deterministic and happens at creation, recomputed whenever a valuation input changes while the contract remains `NEGOTIATING`. The escalator compounds per season: the first season's base is `base_salary_cents`, and each later season's base is `base_salary_cents` grown by `escalator_pct` once per elapsed season — the second season applies the escalator one time, the third season two times, and so on — with every season's base individually rounded half up to a whole cent. The signing bonus is prorated evenly across the term, each season's share rounded half up to a whole cent. Incentives are treated as likely to be earned and are likewise spread evenly across the seasons, again with half-up rounding per season. Each season's cap hit is the sum of that season's base, that season's bonus share, and that season's incentive share; the contract's `aav_cents` is the total of those per-season cap hits divided by `years`, rounded half up to a whole cent. The headline `total_value_cents` is the sum of the per-season bases plus the full signing bonus plus the full incentive pool. The same per-season base projection is available on demand while an agent models proposals, returning the year-by-year base figures across the contract's term.

### 3.5. The Negotiation Cycle: Proposals, Counters, and Cap Reservations

Negotiation proceeds in numbered rounds. An `Agent` drafts a proposal against a contract by naming `proposed_by_agent_id`, the ask `proposed_aav_cents`, and the `proposed_guaranteed_cents`; the draft begins in `DRAFT` and is assigned a `round_index` one greater than the highest round index already used on that contract, so the first proposal carries round index one. Proposals on a contract can be listed and filtered by `status`.

Submission turns a draft into a live market signal and is the first reservation event. Submitting is reserved to the authoring agent, who must be `CERTIFIED` and must equal `proposed_by_agent_id` — failing which the request meets `ERR_AGENT_NOT_CERTIFIED` or `ERR_OWNERSHIP_VIOLATION` respectively — and it requires the contract still be `NEGOTIATING` and the season still be `OPEN`. The request carries the cap-season optimistic-concurrency field described in §2.9. Before the reservation posts, the soft-cap check runs: the season's `committed_cents` plus its `reserved_cents` plus the proposal's `proposed_aav_cents` must not exceed `luxury_threshold_cents`, or the submission is rejected with `ERR_CAP_WOULD_EXCEED`. On success the proposal moves from `DRAFT` to `SUBMITTED` and the season's `reserved_cents` grows by the proposed average annual value.

The team side then answers. Countering — a `Team` act carrying a `counter_aav_cents` figure — moves a `SUBMITTED` proposal to `COUNTERED`, shrinks the season's reservation by the previously proposed figure, grows it again by the counter figure, and rewrites the proposal's own `proposed_aav_cents` to the counter amount. The agent may in turn resubmit, moving the proposal from `COUNTERED` back to `SUBMITTED` with a revised `proposed_aav_cents`; resubmission replays every gate of the initial submission — certified authoring agent, open season, and the soft-cap check evaluated against the new figure — and shifts the reservation from the prior figure to the new one.

Resolution comes in three flavors, and all three drain the reservation. Acceptance, a `Team` act on a `SUBMITTED` proposal, first demands the season still be `OPEN` and then applies the hard-cap check: `committed_cents` plus `proposed_aav_cents` must not exceed `cap_limit_cents`, else `ERR_CAP_HARD_LIMIT`. On acceptance the proposal becomes `ACCEPTED`, its reservation is released from `reserved_cents`, and every sibling proposal on the same contract still sitting in `DRAFT`, `SUBMITTED`, or `COUNTERED` is withdrawn with its reservation released. Rejection, likewise a `Team` act, moves the proposal to `REJECTED` and releases its reservation. Withdrawal is the agent's exit, permitted from `DRAFT`, `SUBMITTED`, or `COUNTERED` and guarded by the same ownership rule as submission: the acting agent must be the proposal's author, failing which the request is rejected with `ERR_OWNERSHIP_VIOLATION`. Withdrawal moves the proposal to `WITHDRAWN`, releasing the reservation where one exists — drafts hold none, so withdrawing a draft touches nothing outside the proposal itself. Acceptance alone does not sign the contract; it merely clears the field for the signing act described next.

### 3.6. Signature, Cap Posting, and Contract Voiding

Signing is the moment paper becomes cap. An `Agent` signs a `NEGOTIATING` contract once at least one of its proposals stands `ACCEPTED`; the signer must be `CERTIFIED`, must be the client's current `primary_agent_id`, and the client must be `ACTIVE`. A request that fails these state preconditions is rejected with `ERR_INVALID_STATE`, while the certification and ownership failures surface `ERR_AGENT_NOT_CERTIFIED` and `ERR_OWNERSHIP_VIOLATION` as usual. The request also carries the contract-level optimistic-concurrency field described in §2.9. A successful signing moves `signing_status` from `NEGOTIATING` to `SIGNED` and, on the parallel ledger dimension, `cap_posting_status` from `UNPOSTED` to `POSTED`. The linked season's `committed_cents` grows by the contract's `aav_cents`; a fee ledger entry of kind `PLAYING_CONTRACT` is written for the contract's gross fee — `aav_cents` multiplied by the agency's `fee_cap_pct`, rounded half up — credited entirely, a `split_pct` of 1.0, to the client's primary agent; and every remaining open proposal on the contract, whether `DRAFT`, `SUBMITTED`, or `COUNTERED`, is withdrawn with its reservation released.

Voiding unwinds the deal and is reserved to an `AgencyManager`. While the contract is still `NEGOTIATING`, voiding moves `signing_status` to `VOIDED` and flips the never-posted ledger dimension from `UNPOSTED` straight to `REVERSED`, withdrawing any open proposals and releasing their reservations. Once a contract is `SIGNED`, voiding is permitted only when no grievance on that contract sits in `FILED`, `UNDER_REVIEW`, or `ARBITRATION` — an open dispute freezes the paper, and the attempt is rejected with `ERR_OPEN_GRIEVANCE`. Voiding a signed contract moves `cap_posting_status` from `POSTED` to `REVERSED`, subtracts the contract's `aav_cents` from the season's `committed_cents`, and voids every fee ledger entry for the contract still standing `ACCRUED`, moving each to `VOIDED`. A contract that is `VOIDED` with posting `REVERSED` is terminal on both dimensions.

### 3.7. Tender and Option Windows

Some contract events live and die by the calendar. An `Agent` or a `Team` principal may place a tender or option on a contract by declaring its `kind` — `QUALIFYING_OFFER`, `TEAM_OPTION`, or `PLAYER_OPTION` — and its exercise window: `window_open_at`, the inclusive start, and `window_close_at`, the exclusive end, which must fall after the open. The record begins `PENDING`, and tenders and options can be listed with filters on `status` or `kind`.

Exercising is the primary agent's act: the acting agent must be `CERTIFIED` and must equal the client's `primary_agent_id`, the contract must stand `SIGNED`, and the logical clock must read on or after `window_open_at` and strictly before `window_close_at` — outside that window the attempt is rejected with `ERR_WINDOW_CLOSED`. A successful exercise moves the record from `PENDING` to `EXERCISED`, stamps `exercised_at` with the current UTC instant, and locks the contract's `base_salary_cents` for the option year at the tender amount. Should the clock reach `window_close_at` with the option unexercised, the system itself moves the record from `PENDING` to `EXPIRED`.

### 3.8. Endorsement Deals and Marketing Income

Marketing money runs on its own rail, kept strictly separate from the playing contract. An `Agent` records an endorsement deal for a client with the `brand_name`, the total `deal_value_cents`, and the deal's `start_date` and `end_date`; the end date must fall after the start date, or creation is rejected with `ERR_WINDOW_CLOSED`. A new deal waits in `PENDING_APPROVAL`, and deals can be listed and filtered by `status`.

Approval is an `AgencyManager` act requiring the client be `ACTIVE` and the agency be `ACTIVE`. At approval the marketing fee is computed. The base rate tiers on deal size: ten percent when the deal value is below 100,000,000 cents — the one-million-dollar line; fifteen percent when the value is at least that figure but below 500,000,000 cents — the five-million-dollar line; and twenty percent once the value reaches five million dollars or more. The payable fee is the smaller of that tiered amount and the agency's marketing ceiling, `deal_value_cents` multiplied by the agency's `fee_cap_pct`, with the result rounded half up to a whole cent and recorded as `agent_fee_cents`. Approval then moves the deal from `PENDING_APPROVAL` to `ACTIVE` and writes a fee ledger entry of kind `ENDORSEMENT` credited entirely to the client's primary agent.

Deals end in two ways. When the logical clock reaches a deal's `end_date`, the system itself moves the deal from `ACTIVE` to `COMPLETED`. An `AgencyManager` may instead terminate an `ACTIVE` deal early, moving it to `TERMINATED` and voiding the deal's fee ledger entry while it is still `ACCRUED`.

### 3.9. Grievances, Arbitration, and the Fee Ledger

When relations sour, an `Agent` files a grievance against a contract, naming `filed_by_agent_id`, a `category` — `NON_PAYMENT`, `ROSTER_MOVE`, `BONUS_DISPUTE`, or `MEDICAL` — a free-text `description`, and the `claimed_amount_cents` sought. The grievance opens `FILED`, and grievances can be listed with filters on `status` or `category`.

Adjudication belongs to the `LeagueOfficer`, and it branches. Starting review moves the grievance from `FILED` to `UNDER_REVIEW`. From there the officer may return the filing for cure — `UNDER_REVIEW` back to `FILED`, a revert loop used to demand additional evidence — or escalate it to `ARBITRATION`, a move permitted only while the disputed contract stands `SIGNED`. Resolution moves an `ARBITRATION` grievance to `RESOLVED` and carries a `resolution_outcome`; when the outcome is `UPHELD`, the system writes a fee ledger entry of kind `TRANSITION_ADJUSTMENT` for the additional fee on the recovered money — `claimed_amount_cents` multiplied by the agency's `fee_cap_pct`, rounded half up — credited entirely to the filing agent. The filing agent may also stand down, withdrawing the grievance from either `FILED` or `UNDER_REVIEW`; only the agent recorded as `filed_by_agent_id` may do so. `RESOLVED` and `WITHDRAWN` are terminal.

Every fee the agency earns, whatever its origin, lands in one book of record: the fee ledger. Each entry carries the owning `agency_id`; a `contract_id` that is null for endorsement-only entries; an `endorsement_deal_id` that is null for playing-contract entries; the `agent_id` receiving the split; the `split_pct` crediting that agent, where the entries written for a single fee event always sum to 1.0; the computed `amount_cents`, derived from the underlying fee multiplied by the split and rounded half up; a `kind` of `PLAYING_CONTRACT`, `ENDORSEMENT`, or `TRANSITION_ADJUSTMENT`; and a `status` that begins `ACCRUED`. An `AgencyManager` settles an accrued entry by marking it `PAID`; entries can also be voided — moving from `ACCRUED` to `VOIDED` — when the underlying event unwinds, as happens when a signed contract is voided or an endorsement deal is terminated. Entries are read through the agency-scoped ledger list, filterable by `agent_id`, `contract_id`, `endorsement_deal_id`, `kind`, and `status`.

For league oversight, a `LeagueOfficer` additionally holds flat, cross-agency read views over every entity type — agents, clients, cap seasons, contracts, proposals, endorsement deals, tender options, grievances, and fee ledger entries — each retrievable by its own `id` and filterable by its natural foreign keys and status fields, among them `agency_id`, `client_id`, `team_id`, `cap_season_id`, `proposed_by_agent_id`, `filed_by_agent_id`, `transition_to_agent_id`, `cert_status`, `signing_status`, `season_year`, and `category`. These views are read-only and exist so that any record referenced from another record can be reached directly.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Read operations and operations that modify an existing resource — including all state transitions — return a `200 OK` status code. Request and response bodies are deliberately not repeated in this table; they are reconstructed from the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a given ISO 8601 UTC instant | LeagueOfficer, AgencyManager |
| POST | `/agencies` | Create a new Agency | LeagueOfficer |
| GET | `/agencies/{agencyId}` | Get an Agency | LeagueOfficer, AgencyManager, Agent, Player |
| POST | `/agencies/{agencyId}/agents` | Register a new Agent under an Agency | AgencyManager |
| GET | `/agencies/{agencyId}/agents` | List Agents of an Agency | LeagueOfficer, AgencyManager, Agent |
| GET | `/agencies/{agencyId}/agents/{agentId}` | Get an Agent | LeagueOfficer, AgencyManager, Agent |
| POST | `/agencies/{agencyId}/agents/{agentId}/certify` | Certify a PENDING agent | AgencyManager |
| POST | `/agencies/{agencyId}/agents/{agentId}/suspend` | Suspend a CERTIFIED agent; in-flight proposals withdrawn | AgencyManager |
| POST | `/agencies/{agencyId}/agents/{agentId}/reinstate` | Reinstate a SUSPENDED agent to CERTIFIED | AgencyManager |
| POST | `/agencies/{agencyId}/agents/{agentId}/revoke` | Revoke certification; clients move to transition | AgencyManager |
| POST | `/agencies/{agencyId}/clients` | Register a new Client under a primary agent | Agent, AgencyManager |
| GET | `/agencies/{agencyId}/clients` | List Clients of an Agency | LeagueOfficer, AgencyManager, Agent, Player |
| GET | `/agencies/{agencyId}/clients/{clientId}` | Get a Client | LeagueOfficer, AgencyManager, Agent, Player |
| POST | `/agencies/{agencyId}/clients/{clientId}/initiate_transition` | Begin a client transfer to a new agent | AgencyManager |
| POST | `/agencies/{agencyId}/clients/{clientId}/complete_transition` | Complete a client transfer; emits fee-split ledger entries | AgencyManager |
| POST | `/agencies/{agencyId}/clients/{clientId}/release` | Release a client; requires no active obligations | AgencyManager |
| POST | `/teams` | Create a Team | LeagueOfficer |
| GET | `/teams/{teamId}` | Get a Team | LeagueOfficer, AgencyManager, Agent, Player, Team |
| POST | `/teams/{teamId}/cap_seasons` | Create a CapSeason for a Team | LeagueOfficer |
| GET | `/teams/{teamId}/cap_seasons` | List CapSeasons for a Team | LeagueOfficer, AgencyManager, Agent, Team |
| GET | `/teams/{teamId}/cap_seasons/{capSeasonId}` | Get a CapSeason including computed available-space projections | LeagueOfficer, AgencyManager, Agent, Team |
| POST | `/teams/{teamId}/cap_seasons/{capSeasonId}/lock` | Lock a CapSeason; open proposals withdrawn | LeagueOfficer |
| POST | `/teams/{teamId}/cap_seasons/{capSeasonId}/unlock` | Unlock a LOCKED CapSeason | LeagueOfficer |
| POST | `/teams/{teamId}/cap_seasons/{capSeasonId}/close` | Close a CapSeason; requires zero reserved space | LeagueOfficer |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts` | Create a Contract; valuation computed at creation | Agent |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts` | List Contracts for a Client | LeagueOfficer, AgencyManager, Agent, Player |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}` | Get a Contract | LeagueOfficer, AgencyManager, Agent, Player, Team |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/sign` | Sign a NEGOTIATING contract; posts to cap and accrues fee | Agent |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/void` | Void a Contract; reverses cap posting and voids accrued fees | AgencyManager |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals` | Create a Proposal in DRAFT | Agent |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals` | List Proposals for a Contract | LeagueOfficer, AgencyManager, Agent, Team |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}` | Get a Proposal | LeagueOfficer, AgencyManager, Agent, Team |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}/submit` | Submit a DRAFT proposal; reserves cap space | Agent |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}/counter` | Team counters a SUBMITTED proposal | Team |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}/resubmit` | Agent re-submits a COUNTERED proposal with a revised number | Agent |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}/accept` | Team accepts a SUBMITTED proposal | Team |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}/reject` | Team rejects a SUBMITTED proposal | Team |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/proposals/{proposalId}/withdraw` | Agent withdraws a DRAFT, SUBMITTED, or COUNTERED proposal | Agent |
| POST | `/agencies/{agencyId}/clients/{clientId}/endorsements` | Create an EndorsementDeal | Agent |
| GET | `/agencies/{agencyId}/clients/{clientId}/endorsements` | List EndorsementDeals for a Client | LeagueOfficer, AgencyManager, Agent, Player |
| GET | `/agencies/{agencyId}/clients/{clientId}/endorsements/{dealId}` | Get an EndorsementDeal | LeagueOfficer, AgencyManager, Agent, Player |
| POST | `/agencies/{agencyId}/clients/{clientId}/endorsements/{dealId}/approve` | Approve a PENDING_APPROVAL deal; computes fee and emits ledger entry | AgencyManager |
| POST | `/agencies/{agencyId}/clients/{clientId}/endorsements/{dealId}/terminate` | Terminate an ACTIVE deal; voids accrued fees | AgencyManager |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/tender_options` | Create a TenderOption on a contract | Agent, Team |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/tender_options` | List TenderOptions for a Contract | LeagueOfficer, AgencyManager, Agent, Team, Player |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/tender_options/{tenderId}` | Get a TenderOption | LeagueOfficer, AgencyManager, Agent, Team, Player |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/tender_options/{tenderId}/exercise` | Exercise a PENDING TenderOption within its window | Agent |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances` | File a Grievance | Agent |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances` | List Grievances for a Contract | LeagueOfficer, AgencyManager, Agent, Player |
| GET | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances/{grievanceId}` | Get a Grievance | LeagueOfficer, AgencyManager, Agent, Player |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances/{grievanceId}/start_review` | Move grievance from FILED to UNDER_REVIEW | LeagueOfficer |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances/{grievanceId}/return_for_cure` | Return an UNDER_REVIEW grievance to FILED | LeagueOfficer |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances/{grievanceId}/escalate` | Escalate an UNDER_REVIEW grievance to ARBITRATION | LeagueOfficer |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances/{grievanceId}/resolve` | Resolve an ARBITRATION grievance; may emit a fee adjustment | LeagueOfficer |
| POST | `/agencies/{agencyId}/clients/{clientId}/contracts/{contractId}/grievances/{grievanceId}/withdraw` | Filing agent withdraws a FILED or UNDER_REVIEW grievance | Agent |
| GET | `/agencies/{agencyId}/fee_ledger_entries` | List fee ledger entries for an Agency | LeagueOfficer, AgencyManager, Agent |
| GET | `/agencies/{agencyId}/fee_ledger_entries/{entryId}` | Get a FeeLedgerEntry | LeagueOfficer, AgencyManager, Agent |
| POST | `/agencies/{agencyId}/fee_ledger_entries/{entryId}/mark_paid` | Mark an ACCRUED entry as PAID | AgencyManager |
| GET | `/agents` | Flat list of Agents across agencies | LeagueOfficer |
| GET | `/agents/{agentId}` | Flat get of an Agent by id | LeagueOfficer |
| GET | `/clients` | Flat list of Clients across agencies | LeagueOfficer |
| GET | `/clients/{clientId}` | Flat get of a Client by id | LeagueOfficer |
| GET | `/cap_seasons` | Flat list of CapSeasons | LeagueOfficer |
| GET | `/cap_seasons/{capSeasonId}` | Flat get of a CapSeason by id | LeagueOfficer |
| GET | `/contracts` | Flat list of Contracts | LeagueOfficer |
| GET | `/contracts/{contractId}` | Flat get of a Contract by id | LeagueOfficer |
| GET | `/proposals` | Flat list of Proposals | LeagueOfficer |
| GET | `/proposals/{proposalId}` | Flat get of a Proposal by id | LeagueOfficer |
| GET | `/endorsements` | Flat list of EndorsementDeals | LeagueOfficer |
| GET | `/endorsements/{dealId}` | Flat get of an EndorsementDeal by id | LeagueOfficer |
| GET | `/tender_options` | Flat list of TenderOptions | LeagueOfficer |
| GET | `/tender_options/{tenderId}` | Flat get of a TenderOption by id | LeagueOfficer |
| GET | `/grievances` | Flat list of Grievances | LeagueOfficer |
| GET | `/grievances/{grievanceId}` | Flat get of a Grievance by id | LeagueOfficer |
| GET | `/fee_ledger_entries` | Flat list of FeeLedgerEntries | LeagueOfficer |
| GET | `/fee_ledger_entries/{entryId}` | Flat get of a FeeLedgerEntry by id | LeagueOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AGENT_NOT_CERTIFIED` | 422 |
| `ERR_OWNERSHIP_VIOLATION` | 422 |
| `ERR_WINDOW_CLOSED` | 422 |
| `ERR_CAP_WOULD_EXCEED` | 422 |
| `ERR_CAP_HARD_LIMIT` | 422 |
| `ERR_RESOURCE_LOCKED` | 409 |
| `ERR_DUPLICATE_ACTIVE_CONTRACT` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS` | 409 |
| `ERR_OPEN_GRIEVANCE` | 409 |

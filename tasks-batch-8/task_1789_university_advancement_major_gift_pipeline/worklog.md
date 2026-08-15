# Worklog — task_1789_university_advancement_major_gift_pipeline

## Step 1: Create Task Directory — 2026-08-14T00:00:00.000Z

Task directory `tasks/task_1789_university_advancement_major_gift_pipeline/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-14T17:44:00.000Z

All three artifacts are complete and pass every check. Final summary:

## Task 1789 — University Advancement & Major Gift Pipeline: scaffold generated

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1789_university_advancement_major_gift_pipeline/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`

**Design profile**: compliance/audit primary archetype with quota/allocation secondary; graph topology (incl. self-referential `Prospect.spouse_prospect_id` and many-to-many `CampaignCreditSplit` junction); cyclic state machines; segregation-of-duties role model; immediate consistency; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Logical-clock test endpoint with pinned default `2026-08-01T00:00:00Z`.

**SCAFFOLD.yaml counts**: 16 entities; 13 state machines (58 transitions, incl. cyclic Proposal negotiation loop, parallel GiftAgreement signature×compliance dims, parallel+cyclic Prospect research×moves dims); 2 OCC concurrency rules (proposal-create-on-Prospect.version, assignment-create-on-Fundraiser.version); 8 calculations (2 dual-variant: campaign FACE_VALUE vs CASH counting, recognition CASH_ONLY vs COMPREHENSIVE); 13 ordered validation priority rows; 64 endpoints; 57 error codes; 6 roles (GiftOfficer entity-backed by Fundraiser, five opaque operational roles).

**Difficulty design**: 21 instances — per rule: dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c: tier branching, split residual rounding, allowance evaluation-order), non_linear_state_machine 3 (three different entities), transitive_cascade 2 (depth-3 payment→installment→pledge→fund; depth-2 write-off→pledge→campaign/recognition), priority_pair_validation_conflict 2 (state×fiscal; safety×referential), boundary_precision_check 3 (ask tier at exactly $1M, portfolio count at max, fund activation at exact minimum), cross_entity_state_dependency 2, resource_temporal_overlap 2 (half-open naming reservation vs closed stewardship periods), compensating_invariant 2 (monetary balances vs portfolio counters). All numeric asserts are pre-computed literals (e.g., CASH 3666667, spendable 4500000→4140000, split 3401/3300/3300, installments [34,33,33]).

**Corner design**: 95 instances = 80 active + 15 `excluded_because` stubs (all stub references resolve to real difficulty instances). Sections: entities 9, state_machines 24, calculations 11, validations 26, endpoints 4, errors 8, rbac 6, cross_cutting_layers 6, consistency_model 1.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1160 calls scanned). Additional audits passed: all 57 errors referenced by validations/transitions AND covered by at least one test; all grounds references resolve; instance names unique across both design files; endpoint roles ⊆ declared roles; no forbidden concurrency vocabulary; every `${var}` placeholder traces to an earlier capture; OCC version payloads are placeholders, never literals.

## Step 3: Copy Shared Files — 2026-08-14T17:47:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1789_university_advancement_major_gift_pipeline/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T18:12:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1789_university_advancement_major_gift_pipeline/workspace/PRD.md` (380 lines). I did not open the two forbidden design files or any other task directory.

## Summary

**Section list**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (headers, 6 roles, identity translation), 2.2 API Response Structure (byte-identical verbatim block — verified programmatically), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock and Scheduled Sweeps, 2.6 Money/Precision/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Nested Resource Retrieval, 2.9 Parallel Status Dimensions / Open Proposals / Hierarchical Consistency, 2.10 Validation Priority Order (13-step first-match-wins chain)
- §3 Business Logic (9 subsections, organized by pipeline chronology): 3.1 Fundraisers & Portfolio Assignments, 3.2 Prospect Intake/Research/Rating, 3.3 Moves Management, 3.4 Proposals (tiers & quorums), 3.5 Gift Agreements & Naming Opportunities, 3.6 Pledges/Installments/Write-Offs, 3.7 Payments/Splits/Reversals, 3.8 Restricted Funds/Endowment/Stewardship, 3.9 Campaigns/Credit/Recognition
- §4 Endpoint Definitions — 64-row table, 4 columns only (Method, Path, Description, Authorized Role)
- §5 Error Code Catalogue — 57-row table, 2 columns only (no trigger conditions)

**Coverage audit results (all PASS)**
- Contract 1 (fields): entities[].fields 104/104 present; endpoint inputs + computed-read keys 79/79; query params 19/19; nested split/allocation/valuation keys also verified — 0 missing
- Contract 2 (rules): all 13 validation priorities expressed as an explicit ordered first-match-wins chain with `applies_to` scopes enumerated (8 ownership operations; stewardship gates on payment+disburse; temporal guards on execute/report-create/payment/pledge); both OCC rules fully specified (`expected_prospect_version` on proposal create, `expected_fundraiser_version` on assignment create, `ERR_STALE_VERSION`/412); all 13 state machines' transitions with preconditions, error ids, and side effects (including cascades: disqualify, supersede, rescind, freeze/unfreeze, reversal reversion); all 8 calculations in precise prose (evidence multipliers 0.6/0.8/1.0 with floor, band thresholds $10M/$1M/$250k/$50k inclusive, affinity 50/30/20 round-half-up, type multipliers 1.0/1.0/0.5, tier boundaries, band-A shift for INDIVIDUAL, split rounding smallest-first/largest-absorbs, front-loaded installment remainder with month-end clamping, FY July 1–June 30 allowance using only pre-FY quarter-ends, 4-of-12 quarters at 4.5% round-half-up, latest-first write-off allocation vs earliest-first payment waterfall); sibling branches (APPROVE/NEGOTIATE/RETURN/REJECT, RESERVED vs OCCUPIED release, both campaign variants, both recognition variants) rendered with equal density
- Contract 3 (§3 path purity): 815 backticked tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos
- All 57 error ids appear in §2/§3 prose; all 64 endpoints appear in §4; all enum/state values present

**Ambiguity-resolution decisions**
1. Cent constants restated with dollar equivalents (e.g., "$250,000 (25000000 cents)") so exact values survive while prose stays natural.
2. `ERR_OPEN_ASK_LOAD_EXCEEDED` expressed at both assignment creation (prospect's open proposals pushing the fundraiser over the ceiling) and proposal submit (`current_open_ask_cents` + ask at most `max_open_ask_cents`, equality allowed), reconciling the validation row with the error-catalog condition.
3. Pledge creation on a non-`EXECUTED` agreement mapped to `ERR_AGREEMENT_INVALID_STATE` (the state-precondition family), since the scaffold defines no pledge-specific error for that gate.
4. Out-of-range `split_pct` attributed to `ERR_SPLIT_PERCENT_SUM_INVALID` per the calculation's validate block; structurally malformed `splits` to `ERR_INVALID_REQUEST` per validation priority 3.
5. §4 "Authorized Role(s)" uses "All roles" for the read endpoints whose scaffold role list is the full six; exact role spellings are fixed in §2.1.
6. Campaign booking requires `ACTIVE` status (from the pledge endpoint description and the `ERR_CAMPAIGN_INVALID_STATE` condition), expressed alongside the inclusive-window `ERR_OUTSIDE_COUNTING_WINDOW` rule.
7. The single audit gap found post-draft — the exact state string `DELIVERED` — was repaired, including the catch-up nuance that an `OVERDUE` report's submission leaves the fund frozen and the agreement lapsed until delivery.

## Step 5: Generate Unit Tests — 2026-08-14T18:32:00.000Z

123 tests collected cleanly. The work is complete.

## Summary

### File inventory

**`test_helpers/`** (8 files):
- `types.py` — 16 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4's "no reduced-property resources"), 22 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 45 endpoint methods covering every PRD §4 row, plus `api_client` singleton
- `api_errors.py` — 59-member `ApiErrorId` enum + `HTTP_STATUS_CODES` map registered via `set_error_http_status_map`
- `assertions.py` — `assert_<entity>()` for all 16 entities
- `factories.py` — 15 payload factories, input fields only
- `constants.py` — `THRESHOLDS` (evidence multipliers, band mins, tier mins, MINIMUM_ACTIVATION_CENTS 2500000, SPENDING_RATE 0.045, MIN_QUARTERS 4, MAX_REMINDERS 3, MATCHED_GIFT_FACTOR 0.5, windows) + `TEST_DEFAULTS`
- `test_users.py` — `TEST_USERS` shared constants (incl. vp-2/dir-2 for quorum and multi-reviewer tests) + `make_gift_officer_headers(user_id)` for the entity-backed `GiftOfficer` role, plus builders for the five opaque roles
- `fixtures.py` — composite helpers: `create_fundraiser`/`create_prospect`/`create_campaign`/`rate_prospect`/`assign_prospect`/`move_prospect`, `setup_rated_assigned_prospect`, `create_proposal_for`/`create_submitted_proposal`/`create_approved_proposal` (tier-aware review routing incl. PRINCIPAL 2-VP quorum), `create_executed_agreement`/`setup_executed_agreement` (with fund reverse-FK lookup), `create_pledge_for`/`setup_active_pledge`, `setup_endowed_fund_active`, `create_payment`, `set_clock`, `find_fund_for_agreement`
- `__init__.py` — barrel re-export of framework generics + all PRD-specific code

**`test_suite/`** (15 files, 123 tests):
- `conftest.py` — session `api` fixture + role-header fixtures
- `test_01_prospect_creation_and_listing.py` (8) — creation defaults, schema rejections, 404, pagination
- `test_02_research_and_moves.py` (7) — assessment review/supersession, capacity rating boundaries, moves machine, re-screen parallel dimensions
- `test_03_disqualify_and_portfolio.py` (6) — disqualify cascade, portfolio capacity boundary, assign/release conservation, deactivation
- `test_04_proposal_lifecycle.py` (11) — creation gates, submit ceilings, submit/review state rules, PRINCIPAL quorum, negotiation cycle, PATCH reset, tier boundary
- `test_05_approval_tiers.py` (4) — trusted-capacity shift (INDIVIDUAL band A), ORGANIZATION exemption, PLANNED 0.5 multiplier, tier-role mapping
- `test_06_agreements_and_naming.py` (9) — drafting gates, naming half-open window (2 tests), retirement, reservation expiry, parallel signature/compliance dimensions
- `test_07_pledges_and_writeoffs.py` (7) — schedule rounding + month-end clamp, reminder cap, overdue strict-> boundary, write-off reject/no-op, terminal lockdown, pledge-type and one-per-agreement gates
- `test_08_payments_cascades_and_reversal.py` (7) — depth-3 activation cascade (2 tests), reversal conservation (2), outstanding boundary, double-reversal, state-beats-fiscal pair (2)
- `test_09_campaigns_and_credit_splits.py` (6) — FACE vs CASH divergence (2), split rounding residual (2), lifecycle gates, inclusive window edge, closed-campaign rejection
- `test_10_recognition_and_societies.py` (5) — CASH_ONLY vs COMPREHENSIVE divergence (2), threshold exact boundary, immediate recognition reconciliation, duplicate level
- `test_11_funds_and_stewardship.py` (12) — activation boundary (2), allowance pinned order (2), MIN_QUARTERS, disbursement caps, closed-interval overlap (2), report lockdown, frozen-fund payment/disbursement gates, safety-beats-referential pair (2), closed fund, valuation uniqueness
- `test_12_writeoff_cascade.py` (2) — latest-first write-off allocation + campaign FACE netting + recognition demotion
- `test_13_security_and_priority.py` (12) — auth 401, cross-role denials, shared GETs, priority ordering (role>schema, existence>ownership, SoD>state), ownership, three SoD self-review denials, OCC 412 on both write paths, version increment, clock monotonicity, not-found catalog, double assignment
- `test_14_retrieval_and_consistency.py` (4) — reverse-FK lookups, filtered agreement list, immediate consistency of `applied_allocations`, open-ask input-set filtering

### Tests per queue
- **Queue A (Difficulty): 43 tests over 21/21 instances** — every instance ≥2 tests
- **Queue B (Corner): 80 tests over 80/80 non-stub instances** — every instance ≥1 test

### Per-instance skip list
None. All 21 difficulty instances and all 80 non-stub corner instances passed the PRD-first two-condition filter — the PRD (§2.10 ordered chain with first-match-wins prose, §3 rule sentences, §5 catalogue) verbatim-covers and uniquely derives every asserted outcome, including the three priority-ordering pairs. The 15 `excluded_because:` stubs were not translated; all their `difficulty_instance` pointers resolve to real difficulty instances (verified programmatically).

### Stage 1/2 self-check results
- Stage 1: `test_helpers` imports cleanly; 68 public client surfaces; entity-backed `GiftOfficer` identity threaded via `make_gift_officer_headers(fundraiser["id"])` in all ownership-gated fixture paths
- Stage 2: 123/123 test functions carry exactly one trailing `Design: Difficulty/...` or `Design: Corner/...` line, all resolving to real instances; 181 docstring quote probes verified verbatim against PRD.md (11 initial probe-window artifacts re-verified as full-string matches; 3 elided quotes rewritten to full verbatim sentences); no `skip`/`skipif`/`xfail` markers; no "scaffold" mentions in generated code; all modules import; `pytest --collect-only` collects 123 tests with no errors.

## Step 6: Generate Implementation — 2026-08-14T18:46:00.000Z

Implementation complete and verified. Summary below.

## File inventory

All under `/home/ubuntu/github/CodingPRD/tasks/task_1789_university_advancement_major_gift_pipeline/workspace/implementation/`:

| File | Purpose |
|---|---|
| `start.sh` | Foreground launcher: guarded `pip install` (no-op when Flask present), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask entry point, blueprint registration, envelope-wrapped error handlers (ApiError / 404 / 405 / catch-all) |
| `db.py` | In-memory store (16 entity dicts) + logical clock starting at exactly `2026-08-01T00:00:00Z`; **no seeding** |
| `errors.py` | `ApiError` + all 52 error-id constants with catalogued HTTP statuses |
| `core.py` | Logical-clock/time math (ISO-8601 3-fractional-digit format, month-end-clamped month arithmetic, fiscal-year start), Decimal floor/round-half-up helpers, response envelope (`meta`/`response_type`/`data`, `limit`/`offset`/`total_count`/`has_more`), auth (`X-User-ID`/`X-User-Role`, 6 roles), request-shape validation, pagination (default 10, min 1, max 100) |
| `services.py` | Domain logic + all 16 serializers (derived counters computed from the graph at read time) |
| `routes/staff.py` | Clock sweep endpoint, fundraisers, assignments |
| `routes/prospects.py` | Prospects, moves, assessments + review, recognition read |
| `routes/proposals.py` | Proposals, agreements, naming opportunities |
| `routes/pledges.py` | Pledges, installments/remind, write-offs + review |
| `routes/payments.py` | Gift payments, waterfall allocation, splits, reversal |
| `routes/funds.py` | Funds, valuations, disburse, stewardship reports + submit/deliver |
| `routes/campaigns.py` | Campaigns lifecycle/totals, recognition societies |

## Endpoint count
**64 routes** — matches the PRD §4 table exactly (verified programmatically against the Flask url_map).

## State machines implemented (11)
Prospect dual-dimension (`research_status` IDENTIFIED/IN_SCREENING/RATED/DISQUALIFIED cyclic + `moves_stage` 6-stage cyclic with system-reserved STEWARDSHIP); ResearchAssessment (SUBMITTED→APPROVED/REJECTED/SUPERSEDED); PortfolioAssignment; Proposal (8 states, cyclic DRAFT loop, PRINCIPAL 2-approval quorum, 90-day expiry sweep, exclusive-approval supersession); GiftAgreement dual-dimension (signature + compliance); RestrictedFund (PENDING_MINIMUM↔ACTIVE threshold, SPENDING_FROZEN, CLOSED); Pledge (ACTIVE→FULFILLED/WRITTEN_OFF/CANCELLED re-evaluation); PledgeInstallment (SCHEDULED/REMINDED/OVERDUE/PAID/WRITTEN_OFF, 30-day overdue sweep, reminder cap 3, reversal reopening); PledgeWriteOff (PENDING→APPROVED/REJECTED); NamingOpportunity (14-day half-open reservations, sweep release, retire); StewardshipReport (DRAFT/SUBMITTED/DELIVERED/OVERDUE with fund-freeze/agreement-lapse cascade and recovery); Campaign (DRAFT→ACTIVE→CLOSED→REPORTED, frozen totals); Fundraiser (ACTIVE→INACTIVE).

## Calculations implemented (7)
`capacity_affinity_rating` (evidence multipliers 0.6/0.8/1.0, floored; band thresholds A–E inclusive lower bounds; affinity 0.5/0.3/0.2 round-half-up); `approval_tier_determination` (type multipliers incl. PLANNED 0.5 round-half-up, tier boundaries, band-A INDIVIDUAL one-step-down shift); `installment_schedule_generation` (front-loaded remainder, calendar-pinned due dates with month-end clamping computed from the original date each step); `pledge_outstanding_balance` (payment waterfall earliest-first, write-off allocation latest-first, PAID/WRITTEN_OFF terminal rules); `credit_split_rounding` (sorted split_pct ASC + index ASC, non-largest round-half-up, largest absorbs residual); `campaign_counted_totals` (FACE_VALUE_BOOKING net of write-offs + non-pledge payments, CASH_RECEIPTS all non-reversed payments, matched factor 0.5 floored per payment, frozen when CLOSED/REPORTED); `endowment_spending_allowance` (FY July 1–June 30, only quarter-ends strictly before FY start, 4–12 quarters, 4.5% of average round-half-up, current-FY disbursements netted); `recognition_society_scoring` (CASH_ONLY membership vs COMPREHENSIVE projection, threshold-primary selection with lower-rank/created_at tie-breaks, lazy persistence).

All money is integer cents via `Decimal` — no floats anywhere.

## Verification
Three smoke suites (211 assertions total) run against fresh-booted servers, all passing: full pipeline (fundraise→rate→assign→move→propose→approve→agree→execute→pledge→pay→split→remind→write-off→reverse→stewardship→recognition), quorum/expiry/rescind/disqualify/PATCH-loop/capacity ceilings, and re-rating cycles/window boundaries/mismatch errors/endowment FY-boundary math. `bash start.sh` verified: empty store, logical clock at the documented default, immediate HTTP readiness.

## PRD interpretation decisions
- **Validation ordering**: followed PRD §2.10 chain strictly (auth → role → shape → existence → ownership → SoD/duplicate → OCC → state → stewardship gates → cross-reference → capacity/tier/uniqueness → temporal → fiscal), including SoD (6) firing before state checks (8) on review endpoints.
- **Execute after reservation lapse**: `ERR_RESERVATION_EXPIRED` when the window lapsed (the sweep has already released the opportunity to AVAILABLE); `ERR_NAMING_OPPORTUNITY_UNAVAILABLE` when OCCUPIED/RETIRED/held by another — per PRD §3.5's explicit error mapping.
- **Derived counters** (fundraiser `current_prospect_count`/`current_open_ask_cents`, prospect giving aggregates, pledge outstanding) are computed from the graph at read time so documented invariants always hold; `version` bumps follow the documented per-event side-effect lists (e.g., fundraiser bumped on submit/reject/supersede/expiry/edit-from-open, not on NEGOTIATE/RETURN).
- **Proposal expiry** blocked by *any* referencing agreement (including RESCINDED), per the literal PRD wording.
- **Write-off requests by FinanceSteward** skip the GiftOfficer ownership check (PRD §3.6: "A GiftOfficer (owning the prospect) or a FinanceSteward").
- **Recognition society selection** is threshold-primary (highest qualifying `threshold_cash_cents`; ties → lower level rank → `created_at` ASC) so the PRD's tie-break rule is non-vacuous; `recognition_society_id` persists lazily on recognition reads without a GET-triggered version bump.
- **Assessment approval on a DISQUALIFIED prospect** computes and stores rating results on the assessment but does not mutate the terminal prospect.
- Out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; unknown query params ignored; unknown body fields rejected everywhere (including `expected_*_version` on non-OCC endpoints).

## Step 7: Run Tests and Iterate — 2026-08-14T19:15:00.000Z

All 8 rounds pass cleanly: 123/123 in every round, union of failures empty. The task is complete.

## Summary

**Iterations run:** 3 sweeps (22 deterministic failures → 3 → 0; every round ran to completion each time).

**Tests deleted:** None wholesale. One assertion removed under STEP 1c (partial-coverage split):
- `test_06_agreements_and_naming.py::test_naming_retire_releases_claim_and_blocks_execute` — removed `assert opp_after["reserved_by_agreement_id"] is None`. Silence category: branch-asymmetric side effect / field-effect silence. PRD §3.5 says a retired RESERVED opportunity's holding agreement "loses its claim" but never states the reservation fields are cleared (contrast rescission's explicit "cleared" and execution's "kept for audit"); two faithful readers diverge. Scaffold rule: `Corner/state_machines/naming_retire_releases_claim_and_blocks_execute`. The verbatim-covered assertions (status RETIRED, execute → `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`, agreement keeps PENDING_SIGNATURE) remain.

**Fixes to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_iso_instant_equal(actual, expected)`: compares ISO 8601 timestamps as parsed instants. PRD pins the *instant* of domain timestamps (reserved_until = clock + 14d; report due_date = period_end + 90d; installment due dates; clock echo) but pins the three-fractional-digit lexical form only for `created_at`/`updated_at`/`api_request_timestamp` (§2.2/§2.4) — string equality was not uniquely derivable.
- `test_helpers/fixtures.py::create_fundraiser` — now accepts `**overrides` (display_name, email, …) passed to the payload factory; two test_13 tests passed those PRD-valid payload fields and died with TypeError before exercising any rule.

**Fixes to `test_suite/`:**
- `test_03::test_disqualify_cascades_...` — `validate_success` + tuple-unpack on a list endpoint → `validate_paginated` (ValueError: data was a 1-element list).
- `test_06::test_agreement_create_on_unapproved_proposal_rejected` — setup replaced `setup_executed_agreement` with `setup_rated_assigned_prospect(move_to="CULTIVATION")`; the old setup moved the prospect to STEWARDSHIP via execution, so the follow-up proposal create was correctly rejected with `ERR_PROSPECT_NOT_SOLICITABLE` (§3.4) — a fixture-constructed precondition violating the tested flow.
- test_06 (4 assertions), test_07 (3), test_11 (1), test_13 (1) — lexical timestamp equality → `assert_iso_instant_equal` (coverage correction; instants still pinned exactly).
- `test_08` — `_written_off_pledge(self)` → `_written_off_pledge(self, api)` + both call sites (NameError).
- `test_11` — three `create_report` calls gained `expected_status=201` (reports are §2.4 resources; §4 create → 201).
- `test_11::TestStewardshipSafetyBeatsReferential._setup` — restructured so the *pledge's own fund* (the credited fund per §3.7) is the frozen one and the payload fund is healthy; the old setup froze only the payload fund and asserted `ERR_STEWARDSHIP_LAPSED` beats `ERR_FUND_PLEDGE_MISMATCH`, not uniquely derivable since §2.10-9 gates the fund the payment "would credit". Under the new setup both readings agree, so the priority-pair assertion is derivable. A seed donor keeps pa's payment ledger clean for the "not recorded" assertion.

**Fixes to `implementation/`:**
- `routes/funds.py::append_valuation` — returns 200, not 201: valuations are entries in `trailing_market_values`, not §2.4 resources; §4 assigns 200 to modify operations (fixed 5 tests).
- `services.py::recompute_campaign_totals` — payments with splits now contribute the HARD split's computed amount to both campaign variants (PRD §3.7 verbatim: "Only the HARD split's amount enters campaign counting (§3.9)"), corporate-matched floor-halving applied to that base.
- `routes/payments.py::create_payment` — credit-split rows are now created before `recompute_campaign_totals` so the HARD-split contribution is visible to the recompute (ordering bug unmasked by the previous fix).

Final state: 8/8 rounds × 123/123 passed, zero failures in the union.

## Step 8: Finalize PRD — 2026-08-14T19:27:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1789_university_advancement_major_gift_pipeline/workspace/PRD_FINALIZED.md`.

## Size delta
- PRD.md: 380 lines / 71,553 chars; PRD_FINALIZED.md: 382 lines / 73,010 chars. Lines +0.53%, chars +2.04%. Five inline edits, no new sections.

## Changes (one bullet per edit)
- §2.5 — insert — new paragraph pinning that every timestamp the API emits (system fields plus all domain timestamps: `reserved_until`, `reservation_expires_at`, `approved_at`, `reversed_at`, `received_at`, `first_due_date`, both `due_date` kinds, `period_start`/`period_end`, `counting_start`/`counting_end`, `quarter_end`, `current_utc`) is rendered ISO 8601 UTC with exactly three fractional digits and `Z` — `implementation/core.py:33-40` (`iso()`), used by `meta_base` (`core.py:105-106`), every `ser_*` in `services.py:421-679`, and `routes/staff.py:42`.
- §3.5 — revise — retirement of a `RESERVED` opportunity sets only `status` to `RETIRED` and leaves `reserved_by_agreement_id`/`reserved_until` in place (contrast rescission/sweep, which clear them) — `implementation/routes/proposals.py:502-516`.
- §3.7 — revise — the fund-state gates examine the *credited fund* (pledge's fund for a pledge-linked payment, else payload `fund_id`), not merely any payload-named fund: `SPENDING_FROZEN` → `ERR_STEWARDSHIP_LAPSED`, `CLOSED` → `ERR_FUND_NOT_ACTIVE` — `implementation/routes/payments.py:123-135`.
- §3.7 — revise — `corporate_matched` payment counts at half its *counted amount* (§3.9), floored, per payment — `implementation/services.py:190-215`.
- §3.8 — insert — a valuation is an entry in `trailing_market_values`, not a §2.4 resource; append returns `200 OK` with the updated fund, not `201` — `implementation/routes/funds.py:51-66`.
- §3.9 — revise — defines a payment's **counted amount** (`amount_cents`, or the HARD split's computed `amount_cents` when splits are present; full, or halved-and-floored when `corporate_matched`); both `FACE_VALUE_BOOKING` and `CASH_RECEIPTS` payment clauses now count "its counted amount" — `implementation/services.py:196-241` (`_counted_amount`, `recompute_campaign_totals`) and split-row creation before recompute at `routes/payments.py:194-213`.

Step 7 items intentionally not turned into edits (pure fixture/test bugs or already-determined behavior): `create_fundraiser(**overrides)` TypeError, `test_03` paginated-vs-object assertion, `test_06` fixture precondition, `test_08` NameError, `test_11` `expected_status=201` (reports are §2.4 resources; §4 already assigns 201 to creates).

## Per-edit pre-edit search log

1. **Timestamp lexical form (§2.5).** (a) Subject: serialization form of all emitted timestamps. (b) Enumerated: `core.py::iso` (sole serializer; grep for `strftime`/`isoformat`/`.iso(` confirms no other path); all `ser_*` users in `services.py` (approved_at, reserved_until, reservation_expires_at, quarter_end, first_due_date, installment/report due_date, received_at, reversed_at, period_start/end, counting_start/end); `meta_base`; `staff.py::set_clock` (`iso(target)`). (c) Listed every emitted field explicitly so no path is excluded; stated only the *emitted* form, leaving input parsing (`parse_dt` accepts offsets/naive) unconstrained.

2. **Naming retire field effects (§3.5).** (a) Subject: `reserved_by_agreement_id`/`reserved_until` on retire. (b) Enumerated: `retire_naming_opportunity` (proposals.py:502-516 — sets status only); `present_agreement` (sets fields, :344-350); `execute_agreement` (keeps for audit, :382-384); `rescind_agreement` (clears, :428-433); `run_sweeps` (c) (clears, services.py:394-399); `list_agreement_naming_reservations` (filters on status, :453-463); `ser_naming_opportunity`. (c) Replaced "changes only the opportunity's `status`" with "sets the opportunity's `status` to `RETIRED` while leaving … in place" to avoid mis-describing the universal §2.4 version/`updated_at` bump that `touch(opportunity)` performs.

3. **Stewardship-gate target (§3.7).** (a) Subject: which fund the `SPENDING_FROZEN`/`CLOSED` payment gates examine. (b) Enumerated: `create_payment` credited-fund derivation and gate order (payments.py:120-138: CLOSED at priority 8, FROZEN at 9, mismatch at 10); the waterfall paragraph's existing "credited fund" definition (services.py callers); `disburse_fund` gates (funds.py:79-82, separate rule, untouched); `reverse_payment` (no gate on reversal — wording scoped to payment recording only). (c) Wording covers both gate errors and the mixed-failure case (payload fund frozen but pledge's fund healthy → mismatch, not stewardship-lapsed), matching impl exactly.

4. **Corporate-matched clause (§3.7).** (a) Subject: halving base when splits exist. (b) Enumerated: `_matched_amount`/`_counted_amount` (services.py:190-215) — halving applies after HARD-base substitution; all `recompute_campaign_totals` callers (payments.py:213,295; pledges.py:94,247; proposals.py:441). (c) Pointed at "counted amount (§3.9)" instead of "its amount" to avoid contradicting the HARD-base rule.

5. **Valuation 200 (§3.8).** (a) Subject: status code of `POST /funds/{id}/valuations`. (b) Enumerated: `append_valuation` returns `success_object(ser_fund(fund), 200)`; §2.4 resource list excludes valuations; §4's create→201/modify→200 rule; response body is the updated fund per §2.2's create-or-modify rule. (c) Explicitly named "not a standalone resource in the sense of §2.4" and "with the updated fund" so the sentence stays consistent with §2.2's body rule and §4's table row.

6. **Counted-amount definition (§3.9).** (a) Subject: payment contribution to both campaign variants. (b) Enumerated: `recompute_campaign_totals` (face ignores pledge-linked payments, counts pledges net-of-written-off in window by `created_at`; cash counts all non-reversed in-window payments); `_counted_amount` HARD-base + matched halving; split-row creation preceding recompute (payments.py:194-213); freeze for CLOSED/REPORTED (services.py:223-225) matching §3.9's "totals freeze"; reversal exclusion via `not g["reversed"]`. (c) Inserted a single counted-amount definition and changed both variant clauses to reference it, keeping the pledge-counting clause and §3.7's "Only the HARD split's amount enters campaign counting" verbatim; verified no leftover occurrences of "full-or-floored-half"/"half its amount"/"full amount" remain.

## Step 9: Complete PRD — 2026-08-14T19:44:00.000Z

All changes are in place. The diff confirms 16 lines changed in place (no lines added or removed — pure inline inserts/revisions), 382 lines in both files, char delta +2125 (73261 → 75386).

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1789_university_advancement_major_gift_pipeline/workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md 382 lines / 73,261 chars → PRD_COMPLETED.md 382 lines / 75,386 chars (char-delta +2125; 16 lines revised inline, 0 lines added/removed, no new sections).

**Counts:** 13 ambiguity-pins, 4 mismatch-revisions (17 changes across 16 lines).

**Changes:**

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative/non-integer `offset` rejected with `ERR_INVALID_REQUEST` — implementation/core.py:238-259
- §2.3 — revise — ambiguity — default list sort is `created_at` ascending with ties broken by `id` ascending — implementation/core.py:266
- §2.4 — revise — ambiguity — `version` starts at 1 at creation with `created_at` == `updated_at` — implementation/core.py:278-286
- §2.4 — insert — mismatch — "increments on every mutation" is absolute in prose but impl exempts two derived-field updates: campaign `face_value_counted_cents`/`cash_counted_cents` recomputation and the lazy recognition-society refresh advance no `version`/`updated_at` — implementation/services.py:222-241, 180-183
- §2.10 item 3 — insert — ambiguity — endpoints declaring no request-body fields accept and ignore any supplied body (no unknown-field rejection there) — implementation/routes/proposals.py:158, implementation/routes/prospects.py:87
- §3.2 — insert — ambiguity — a supplied `spouse_prospect_id` that does not resolve is rejected with `ERR_PROSPECT_NOT_FOUND` — implementation/routes/prospects.py:42-43
- §3.2 — revise — ambiguity — every assessment filing advances the prospect's `version` by 1, including a filing against an already `IN_SCREENING` prospect (no status change) — implementation/routes/prospects.py:234-236
- §3.2 — insert — ambiguity — approving an assessment whose prospect is `DISQUALIFIED` still records the three rating results on the assessment (`APPROVED`) but leaves the prospect untouched and runs no supersession — implementation/routes/prospects.py:284
- §3.5 — insert — ambiguity — execution moves the prospect to `STEWARDSHIP` only from `CULTIVATION`/`SOLICITATION`/`NEGOTIATION`; a prospect in any other stage keeps stage and version — implementation/routes/proposals.py:400-403
- §3.5 — revise — mismatch — rescission closes the established fund to `CLOSED` unconditionally; dropped "which requires its `balance_cents` to be zero" (no such guard exists; reachable with non-zero balance after disbursement + reversal) — implementation/routes/proposals.py:447-449
- §3.7 — insert — ambiguity — the recorded payment's `fund_id` is the credited fund's id (pledge's fund for pledge-linked payments even when the payload omitted `fund_id`), null when no fund is credited — implementation/routes/payments.py:123-128, 152
- §3.7 — revise — ambiguity — on the payment waterfall, an installment fully covered through a mix of payments and write-offs while holding `paid_cents` above zero also becomes `PAID` — implementation/routes/payments.py:176-179
- §3.8 — revise — ambiguity — current-use funds keep both `spendable_fy_cents` and `allowance_remaining_cents` at zero — implementation/services.py:343-344
- §3.8 — revise — mismatch — `CLOSED` is reached through rescission of the establishing agreement, dropping the "with a zero balance" condition — implementation/routes/proposals.py:447-449
- §3.9 — revise — mismatch — campaign close freezes totals: new payments/pledge bookings referencing it are rejected, but write-off approvals, pledge cancellations, and payment reversals touching a closed campaign proceed normally with totals unchanged (impl recomputes are no-ops when not `DRAFT`/`ACTIVE`; PRD had said such write-offs "are rejected") — implementation/services.py:223-225, implementation/routes/pledges.py:244-247, implementation/routes/payments.py:292-295
- §3.9 — revise — ambiguity — society membership is picked by highest qualifying `threshold_cash_cents` (not highest level), with the pre-existing shared-threshold tie-breaks unchanged — implementation/services.py:156-162
- §3.9 — insert — ambiguity — the lazy recognition refresh on a recognition read updates `recognition_society_id` in place without advancing the prospect's `version`/`updated_at` — implementation/routes/prospects.py:188-197

Everything else in the implementation (endpoint inventory, role maps, validation-priority chain, state machines, all calculation formulas and rounding modes, sweep rules, envelope/error shapes, 200/201 conventions) was verified to already be pinned uniquely by the PRD and required no change.

# Worklog — task_1480_media_rights_broadcast_deal_administration

Scenario: Media Rights & Broadcast Deal Administration (sports league media rights office): rights package definition by territory/platform/window, bidding process & exclusivity terms, rights fee payment schedule & escalators, production obligations (number of games/programs) & make-goods, sublicensing approval & blackout rules, audience delivery guarantee & rating shortfall remedy, contract renewal & matching rights, rights conflict monitoring

Difficulty target: harder than expert level.

## Step 1: Create Task Directory — 2026-08-13T11:39:00.000Z

Task directory `tasks/task_1480_media_rights_broadcast_deal_administration/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-13T11:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1480_media_rights_broadcast_deal_administration/workspace/INSTRUCTION.md` (1424 bytes). Done out of order (before Step 2 completes) since it has no dependency on scaffold generation.

## Step 2: Generate Scaffold — 2026-08-13T12:21:00.000Z

All 9 rules have exactly 2 instances each (=18 difficulty instances). Corner design has 19 active instances + 1 excluded stub = 20 entries. All 38 names unique across both files.

Final summary:

## Scaffold Generation Summary — task_1480_media_rights_broadcast_deal_administration

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1480_media_rights_broadcast_deal_administration/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

### Counts
| Artifact | Count |
|---|---|
| Entities | 13 |
| State machines | 11 (58 transitions total) |
| Calculations | 7 |
| Validations | 20 |
| Endpoints | 90 |
| Errors | 65 |
| Roles | 5 |
| Concurrency rules (OCC) | 2 |
| §1.8 difficulty instances | 18 (2 per rule × 9 rules) |
| §1.9 corner instances | 19 active + 1 excluded stub |

### Notable design decisions

1. **Archetype blend**: `multi_party_negotiation` (bidding/counter-offer/renewal matching) × `compliance_audit` (blackouts, bar/suspend, breach termination). Role model = `segregation_of_duties` — `RightsManager` vs `ComplianceOfficer` cannot perform each other's termination actions.

2. **Entity topology**: hybrid with **self-referential Bid** (`parent_bid_id` for counter-offer rounds) and **cross-aggregate** Deal → Bid/Broadcaster references.

3. **Compound state machine on Deal**: dual state dimensions — `status` (DRAFT→EXECUTED→ACTIVE→RENEWAL_OPEN→…⟶TERMINATED) × `posture` (CLEAN | WARNING | FROZEN), posture derived from children states per `deal_posture_rule`.

4. **Cyclic state machine on Bid**: SHORTLISTED → COUNTERED → (successor bid round_number+1) → SUBMITTED → … — a negotiation loop supporting Rule 3 (non-linear shape).

5. **Dual-variant calculation (Rule 1)**: `rating_shortfall_remedy` has `provisional_remedy` vs `final_remedy` variants that produce different liabilities (16666667 vs 10000000 cents) for identical data due to different input-set filters.

6. **Combinatorial formulas across modes (Rule 2)**: (a) `escalated_rights_fee` uses nested max(compounded, growth_floor) then min(pre_cap, cap) with 3-input non-linear interaction; (b) `payment_schedule_allocation` pins per-milestone round_half_up + remainder reconciliation order.

7. **Asymmetric interval semantics (Rule 8)**: `exclusivity_conflict_check` uses half-open `[start, end)` on packages; `sublicense_blackout_overlap` uses half-open sublicense ∩ CLOSED blackout — producing observable boundary asymmetry (S.end == B.start does NOT intersect; S.start == B.end DOES).

8. **OCC on two parents**: `Deal.version` gates `/execute` (ERR_STALE_DEAL_VERSION, 412); `RightsPackage.version` gates `/accept` (ERR_STALE_PACKAGE_VERSION, 412).

9. **Logical clock**: `POST /_clock/set_current_utc` with default `2026-08-01T00:00:00Z`, drives time-sensitive transitions (INVOICED→OVERDUE, RENEWAL_OPEN→LAPSED, etc.).

10. **Topology choice**: I switched from nested (`/rights-assets/{aid}/packages/{pid}/…`) to flat (`/packages`, `/deals`, `/bids`, …) URL routing with `asset_id` / `deal_id` / `package_id` as body/query FK params. This both (i) fits the lint's `derive_entity_collection_segments` heuristic and (ii) aligns with the skill's guidance that **flat topology is under-represented** in existing examples. To anchor each child collection's canonical segment, I added flat single-GET endpoints (`/bids/{id}`, `/payment-milestones/{id}`, etc.) plus flat filtered-list endpoints (`/bids?package_id=…`, etc.) for FK reverse-reachability.

## Step 4: Generate PRD — 2026-08-13T12:58:00.000Z

**Output:** `workspace/PRD.md` — 406 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications & System-Wide Principles: 2.1 RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination and List Filtering, 2.4 The Logical Clock and Time-Driven Transitions, 2.5 Common Resource Properties, 2.6 Money/Basis Points/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Nested Path Validation, 2.9 Broadcast Windows and Interval Semantics, 2.10 Deal Posture (CLEAN/WARNING/FROZEN), 2.11 The Rights Conflict Monitor, 2.12 Validation Order and Error Precedence
- §3 Business Logic & Workflows (9 subsections): 3.1 Asset & Package Definition, 3.2 Broadcaster Registration/Accreditation/Discipline, 3.3 Bidding Cycle & Award, 3.4 Deal Execution & Escalated Fee Schedule, 3.5 Invoicing/Collections/Delinquency/Default, 3.6 Production Obligations & Broadcast Events, 3.7 Audience Measurement & Ratings Guarantee, 3.8 Sublicensing & Blackout Governance, 3.9 Renewal/Matching Rights/Deal Termination
- §4 Endpoint Definitions (90 endpoints, 4-column table)
- §5 Error Code Catalogue (65 errors, 2-column table)

**Coverage audit (all scaffold sections reflected):**
- `entities` — all 13 entities' fields covered; Contract 1 check: 116/116 required identifiers present in backticks, 0 missing. `RightsConflict`'s `common_fields: false` exception stated explicitly.
- `state_machines` — all 12 machines, every transition's from/to states, preconditions paired with error IDs, and side effects in prose (verified machine-by-machine).
- `calculations` — all 7 rendered as precise prose (escalated fee with growth floor/cap and season-1 invariant; payment allocation with per-milestone half-up rounding and one-cent remainder distribution; rating shortfall remedy at 0.25 rate with both variants; make-good credit with 1.5 aggravation multiplier above 20% shortfall; half-open exclusivity overlap; half-open-vs-closed blackout intersection incl. adjacency asymmetry; posture ladder with thresholds 3 / 30 days / 70%).
- `validations` — all 20 priorities expressed: global pipeline (auth → role → existence → state → business) in §2.12 plus explicit per-endpoint orderings.
- `concurrency_rules` — both OCC rules fully expressed with endpoint, required `expected_*_version` field, exact error ID and HTTP 412.
- `response_envelope` — §2.2 verbatim; pagination defaults (limit 10/1/100, offset 0, `created_at` ascending, meta fields) in §2.3.
- `endpoints` — all 90 paths verified present in §4 with correct roles; all side effects narrated in §3.
- `errors` — all 65 IDs verified present both in the §5 table and in §2/§3 narrative.
- `roles` — all 5 roles with exact spelling and identity semantics (BidCoordinator entity-backed by `Broadcaster`; the other four opaque) in §2.1.

**Contract 3 (§3 path purity):** 533 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

## Step 5: Generate Unit Tests — 2026-08-13T13:35:00.000Z

**`test_helpers/`** (8 modules): `types.py` (13 entity TypedDicts, 15 status enums; `RightsConflict` correctly omits `updated_at`/`version` per append-only rule), `api_client.py` (75 endpoint methods, incl. all flat read anchors), `api_errors.py` (67 error IDs → HTTP statuses, registered via `set_error_http_status_map`), `assertions.py` (per-entity + deal-invariant checkers), `factories.py`, `constants.py` (breach threshold 3, late-fee 0.0005/day, aggravation 1.5 @ >0.20, remedy 0.25, startup clock), `test_users.py` (5 roles + `make_bid_coordinator_headers` for the entity-backed BidCoordinator), `fixtures.py` (5-tier composite chains: market → award → executed → active deal, event delivery, sublicense/blackout helpers; all fixture due dates sit on/after the 2026-08-01 startup clock; overdue states are reached by forward clock advance only).

**`test_suite/`** — conftest + 7 files, 55 tests:

| File | Tests | Queues |
|---|---|---|
| test_01_creation_validation_rbac.py | 8 | 8 Corner |
| test_02_bidding_and_award.py | 12 | 8 Difficulty + 4 Corner |
| test_03_deal_execution_and_fee_schedule.py | 6 | 4 Difficulty + 2 Corner |
| test_04_payments_delinquency_posture.py | 7 | 6 Difficulty + 1 Corner |
| test_05_production_audience_and_remedies.py | 9 | 8 Difficulty + 1 Corner |
| test_06_sublicensing_blackout_conflicts.py | 7 | 6 Difficulty + 1 Corner |
| test_07_discipline_cascades.py | 6 | 4 Difficulty + 2 Corner |

**Queue A (Difficulty): 36 tests — all 18 instances × ≥2. Queue B (Corner): 19 tests — all 19 non-stub instances × 1.** The single stub (`Corner/errors/error_bid_below_floor_triggerable`) was not translated; its cross-reference to `boundary_precision_check/bid_floor_exact_equality` resolves.

**Instances skipped: 0.** No `skip`/`skipif`/`xfail` markers anywhere.

**Stage 2 self-audit verdict: PASS** — all 55 tests carry exactly one Design tag; every tag resolves to a real instance in the source YAML; every ≥8-word quoted docstring span greps verbatim in `workspace/PRD.md`; all files compile; all `test_helpers` imports resolve.

**Notable adaptations (recipe defects corrected against the PRD, assertions unchanged in substance):**
- Several recipes used milestone due dates *before* the 2026-08-01 startup clock or moved the clock backward. PRD §2.4 only sanctions forward "advance", so fixtures invoice on-time first, then advance forward past the due date.
- `broadcaster_bar_cascades...`: the recipe's bar call would fail `ERR_NO_BREACH_DEAL` (no pre-existing breach deal). Fixture builds deal 1 → 3 overdue milestones → terminate-breach (auto-suspends) → then bar cascades onto deal 2. Second test for the instance exercises the direct §3.9 breach-termination cascade.
- `state_vs_business_safety...`: PRD §3.3 places the BROADER-grade check at bid *filing* and the package-state gate at *submission*, so the dual-violation-on-submit scenario is unreachable; the instance is covered by two isolated tests (submit-on-withdrawn → 409; BROADER+SPECULATIVE file → 422).
- `business_temporal_vs_business_fiscal...`: recipe left the deal EXECUTED, where terminate-convenience would hit the state gate, not the fiscal one. Added an on-time-paid second milestone (weights rebalanced to sum 1.0) so the deal is ACTIVE and `ERR_OUTSTANDING_DELINQUENCY` genuinely fires; declare-default is attempted one hour past due so it precedes any positive `DEFAULT_GRACE_DAYS`.
- `deal_total_contracted_fee_computed`: recipe's package window exceeded the asset season (would fail lock validation). Package window kept inside the 2026 season while the deal term spans two full seasons; assertion (205000000) unchanged.
- `make_good_credit_conserves...`: the REMEDIED path is unreachable from the API (no endpoint raises `credit_settled_cents`), so the compensating leg uses the PRD-verbatim `forgive-credit` path (accrued credit returns to 0, obligation CREDITED) instead.
- Exact late-fee values asserted (1 day → 500; 28 days → 14000) match the design index's pre-computed expectations under the natural reading of §3.5's finalization formula.

## Step 6: Generate Implementation — 2026-08-13T13:35:00.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### File list
- `start.sh` — executable launcher; guards `pip install` behind a flask import check, then `exec python3 app.py`
- `requirements.txt` — flask>=2.2,<4.0
- `app.py` — Flask entry point, error handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores (13 collections, empty at boot, no seeding)
- `errors.py` — `ApiError` + full 63-entry error catalog with exact IDs/HTTP statuses
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields)
- `middleware.py` — `X-User-ID`/`X-User-Role` validation, five roles, 400 → 403 chain
- `util.py`, `serializers.py` — payload validation, pagination, ISO-8601-with-millis serialization
- `services/clock.py` — logical clock pinned at `2026-08-01T00:00:00Z` (never wall-clock)
- `services/calculations.py` — escalated_rights_fee, payment_schedule_allocation, make_good_credit, rating_shortfall_remedy, deal_posture_rule ladder, exclusivity/blackout interval scans
- `services/system.py` — clock-driven transitions (INVOICED→OVERDUE, RENEWAL_OPEN→LAPSED, offer OPEN→LAPSED)
- `routes/` — clock, assets, broadcasters, packages, bids, deals, payment_milestones, production, sublicense (+ blackout windows), renewals (+ rights conflicts)

### Endpoint count
All 74 scaffold endpoints implemented (90 in PRD table incl. flat list/get anchors): 1 clock admin, 7 asset, 8 broadcaster, 5 package (+nested bid list/get), 12 bid lifecycle, 7 deal lifecycle, 9 payment-milestone (nested + flat), 8 production-obligation, 9 broadcast-event, 9 audience-measurement, 9 sublicense-request, 3 blackout-window, 8 renewal-offer, 2 rights-conflict.

### State machine coverage
All 11 entity state machines implemented with scaffold-exact preconditions and error IDs (asset lock/close/retire; broadcaster discipline cascades; full bid cycle incl. counter-offer round inheritance; deal lifecycle; milestone late-fee finalization; obligation remedies; event outcomes; measurement dispute path; sublicense revoke with blackout-conflict logging; renewal match/exercise/lapse with incumbent ownership checks).

### Calculation coverage
Escalated fee with compound vs. growth-floor max and cap; season-fee allocation with per-milestone HALF_UP rounding and one-cent remainder distribution; late fees at 0.0005/day; make-good credit with 1.5x aggravation over 20% shortfall capped at season fee; rating shortfall remedy at 0.25 rate; deal posture ladder (FROZEN on default/delinquency≥3/stale shortfall; WARNING on 1-2 delinquency/shortfall/rating<70%); exclusivity conflict scan (half-open) and sublicense-blackout scan (half-open ∩ closed asymmetry per PRD §2.9).

### Validation & OCC coverage
Full priority-ordered validation: auth (400) → role (403) → left-to-right path existence with resource-specific 404s → state 409s → ordered business rules (safety → constraint → temporal → referential → fiscal) with exact error IDs. Both OCC writes enforced (`expected_deal_version` on execute → 412 ERR_STALE_DEAL_VERSION; `expected_package_version` on accept → 412 ERR_STALE_PACKAGE_VERSION). BidCoordinator entity-backed ownership enforced on renewal match/withdraw.

### Boot verification
`bash start.sh` confirmed: install-guard dependencies, foreground via `exec`, bind `0.0.0.0:$PORT`, respond within ~2s, completely empty store across consecutive boots, logical clock exactly `2026-08-01T00:00:00Z` before any set call. Four end-to-end suites all pass.

NOTE (orchestrator): Step 5 reported 67 error IDs in api_errors.py vs Step 6's 63-entry catalog — Step 7 will arbitrate against PRD.

## Step 7: Test/iterate loop — 2026-08-13T14:30:00.000Z

Baseline sweep: 50/55 in all 8 rounds (5 deterministic failures, zero flakiness).
Error-catalog arbitration: api_errors.py, implementation/errors.py, and PRD §5 all carry exactly 65 IDs with identical HTTP statuses — the reported 67/63 discrepancy was stale; no change needed. No tests deleted.

Failures → fixes:
1. `test_execute_with_stale_deal_version_rejected` (assert 1 != 1) — PRD §2.7 verbatim names milestone creation as a deal amendment advancing `version`; `routes/payment_milestones.py::create_milestone` never touched the deal. Implementation fix: `touch(deal)` after allocation recompute.
2. `test_record_payment_cures_and_restores_count` (WARNING vs CLEAN) — PRD §2.10 gates the rating-based WARNING clause on "evaluated at season close"; `services/calculations.py::evaluate_posture` applied it unconditionally. Implementation fix: `_season_close_reached(deal)` gate (asset season_end_date extended per extra term season).
3. `test_approve_on_frozen_deal_rejected` (setup 409 ERR_MILESTONE_NOT_SCHEDULED) — test double-invoiced the December milestone (loop invoiced all 4, then `pay_milestone_on_time` re-invoiced). PRD §3.5 requires SCHEDULED for invoice; implementation correct. Test fix: invoice only milestones[:3].
4. `test_withdrawal_cascades_to_submitted_bid` (NameError) — `setup_submitted_bid` used but missing from test_07 imports. Test fix: added import (exported via fixtures `*`).
5. `test_bar_cascades_to_deals_and_milestones` (409 ERR_DEAL_NOT_ACTIVE) — test terminate-breached deal1 while still EXECUTED; PRD §3.9 restricts breach termination to ACTIVE deals. Test fix: deal1 gets a 4th milestone (weights rebalanced 0.25×4) paid on time → ACTIVE. Also surfaced a latent implementation gap: §3.9 suspends the broadcaster "per §3.2", and §3.2 suspension carries market consequences (reject PENDING sublicenses on the broadcaster's deals, withdraw live bids on OPEN_FOR_BIDS packages); `terminate_breach` set the status without the cascade. Implementation fix: shared `suspend_broadcaster_with_consequences()` in `services/system.py`, used by both `broadcasters.suspend` and `deals.terminate_breach`.

Post-fix sweep: 55/55 in all 8 parallel rounds. CLEAN.

## Step 7: Run Tests and Iterate — 2026-08-13T14:10:00.000Z

Clean 8-round parallel sweep achieved: **55/55 passed in every round**.

**Iterations run:** 2 (baseline sweep → fixes → verification sweep)

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule with unique derivability.

**Error-catalog arbitration (known discrepancy):** Stale — `test_helpers/api_errors.py`, `implementation/errors.py`, and PRD §5 all carry exactly **65** error IDs with identical HTTP statuses. No change needed.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_sublicensing_blackout_conflicts.py` — `test_approve_on_frozen_deal_rejected`: setup double-invoiced the December milestone (PRD §3.5 requires SCHEDULED for invoice); now invoices only the three September milestones and lets `pay_milestone_on_time` handle the fourth.
- `test_suite/test_07_discipline_cascades.py` — `test_withdrawal_cascades_to_submitted_bid`: added missing `setup_submitted_bid` import (NameError).
- Same file — `test_bar_cascades_to_deals_and_milestones`: deal1 was breach-terminated while still EXECUTED, violating PRD §3.9's ACTIVE precondition; rebalanced deal1 to four 0.25-weight milestones with the first paid on time so the deal reaches ACTIVE, preserving the delinquency-count-3 breach condition.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/payment_milestones.py` — `create_milestone`: added `touch(deal)`; PRD §2.7 verbatim names milestone creation as a deal amendment that advances the deal `version` (drives `ERR_STALE_DEAL_VERSION`).
- `workspace/implementation/services/calculations.py` — `evaluate_posture`: rating-based WARNING now gated by new `_season_close_reached()` helper; PRD §2.10 applies that clause only "evaluated at season close" (previously unconditional, so every executed deal with unmet rating read WARNING before season end).
- `workspace/implementation/services/system.py` — added `suspend_broadcaster_with_consequences()` implementing the full §3.2 suspension (status + bid-withdrawal and PENDING-sublicense-rejection cascades).
- `workspace/implementation/routes/deals.py` — `terminate_breach` now suspends "per §3.2" via the shared helper (previously set status without the §3.2 market consequences).
- `workspace/implementation/routes/broadcasters.py` — `suspend` refactored to use the same shared helper (behavior unchanged).

## Step 8: Finalize PRD — 2026-08-13T14:30:00.000Z

`PRD_FINALIZED.md` written with exactly two inline edits, both tracing to `implementation/` fixes in `<step_7_diff>`.

**Line counts:** PRD.md 406 lines; PRD_FINALIZED.md 406 lines — 0% delta; both edits inline within existing paragraphs.

**Changes:**
- **§2.10** — insert — added two sentences defining "season close" for the rating-based WARNING clause: reached only when the logical clock is strictly later than the end of the deal's final season, where end of season n = asset `season_end_date` + (n−1) season lengths (one season length = `season_end_date` − `season_start_date`), and season count = term length in whole days / 365 rounded to nearest, minimum 1 — `implementation/services/calculations.py:160-171` (`_season_close_reached`), with season count from `calculations.py:62-73` (`deal_season_count`)
- **§3.9** — revise — breach-termination sentence "the deal's broadcaster is suspended per §3.2" now carries the condition "only when the broadcaster is currently `ACCREDITED`; if it is in any other status, its status is left unchanged and the termination proceeds regardless, without error" — `implementation/routes/deals.py:157-163` (`terminate_breach` guard) via `implementation/services/system.py:47-68` (`suspend_broadcaster_with_consequences`)

**Step-7 items requiring no edit (PRD already determines behavior):**
- `create_milestone` `touch(deal)` — §2.7 verbatim already names milestone creation as a deal amendment advancing version.
- `suspend_broadcaster_with_consequences` helper / `broadcasters.suspend` refactor — §3.2 already spells out the cascades; refactor behavior-neutral.
- All three `test_suite/` fixes — pure fixture bugs against already-pinned rules (§3.5 SCHEDULED-for-invoice, §3.9 ACTIVE precondition, missing import).

**Per-edit pre-edit search log:**
- **Edit 1 (§2.10 season close).** (a) Subject: temporal gate on rating-based WARNING clause. (b) Paths enumerated: `calculations.py:193-197` (clause incl. `commit > 0` guard), `calculations.py:160-171` (`_season_close_reached`), `calculations.py:62-73` (`deal_season_count`); all `refresh_posture` callsites (`routes/deals.py:97`, `services/system.py:26`, `routes/production.py:147,164,183,282,422`, `routes/payment_milestones.py:151,158,171,197`); `routes/production.py:47-55,135-137` (`_season_end_for` — same formula); `calculations.py:148-157` (`rating_shortfall_remedy` — dead code, no behavioral anchor); `routes/renewals.py:156` (renewal extends term_end). (c) Adjustments: scoped with "for the purposes of this rating-based WARNING clause"; phrased as a gate not an automatic flip; "whole days (any partial day discarded)" for timedelta.days flooring; rounding tie-break deliberately unnamed (unobservable); pre-execution fallback omitted as unreachable.
- **Edit 2 (§3.9 suspension condition).** (a) Subject: broadcaster-suspension step of breach termination when broadcaster not ACCREDITED. (b) Paths enumerated: `routes/deals.py:157-163` (`terminate_breach` — helper called only when broadcaster ACCREDITED, no error otherwise); `services/system.py:47-68` (helper cascades); `routes/broadcasters.py:81-88` (suspend endpoint — pre-checks ACCREDITED with `ERR_BROADCASTER_NOT_ACCREDITED`); `routes/broadcasters.py:91-131` (reinstate, bar — bar does not invoke suspension helper); repo-wide grep confirming `services/system.py:53` is the only suspension path. (c) Adjustments: kept "suspended per §3.2" by reference; appended locally-scoped condition rather than restating §3.2's gate as an error (impl raises nothing from the cascade).

## Step 9: Complete PRD — 2026-08-13T15:05:00.000Z

**Produced:** `workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md 406 lines / 63,314 bytes → PRD_COMPLETED.md 408 lines / 68,969 bytes. Char delta **+5,573 chars** (+5,655 bytes), 24 changed line regions, no new sections, all changes inline.

**Counts:** 29 ambiguity-pins, 8 mismatch-revisions.

### Ambiguity-pins (PRD silent → pinned to impl)

- §2.1 — insert — "malformed" headers = empty value or unrecognized role name — `implementation/middleware.py:21-26`
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `implementation/util.py:136-158`
- §2.3 — insert — list sort ties broken by `id` — `implementation/util.py:189-190`
- §2.3 — insert — `has_more` = `offset` + returned items < `total_count` — `implementation/response.py:39`
- §2.4 — insert — clock settable to any valid instant (non-monotonic allowed); bad `to_iso8601` → `ERR_INVALID_REQUEST` — `implementation/services/clock.py:17-20`, `implementation/routes/clock.py:18-22`
- §2.5 — insert — `version` starts at 1 on creation — `implementation/util.py:21`
- §2.5 — insert — all entity timestamps (`created_at`/`updated_at`/`detected_at`) stamped from the logical clock — `implementation/util.py:17`, `implementation/services/calculations.py:235-236`
- §2.7 — insert — missing/non-integer version field → `ERR_INVALID_REQUEST` (400); version check runs after path resolution, before state/business checks — `implementation/routes/deals.py:55-63`, `implementation/routes/bids.py:253-263`
- §2.8 — insert — body-carried ids (`asset_id`, `bidder_id`, `parent_bid_id`, `obligation_id`, `broadcast_event_id`, `offeror_broadcaster_id`) resolve to the same per-kind 404 family — `implementation/routes/packages.py:45-46`, `bids.py:66-67`, `production.py:195-199`
- §2.9 — insert — exclusivity scan also runs at lock-packages time — `implementation/routes/assets.py:103-104`
- §2.10 — insert — internal (non-serialized) `shortfall_declared_at` / frozen-since instants; durations in whole elapsed days — `implementation/services/calculations.py:185-187,205-209`, `implementation/serializers.py:32`
- §2.11 — insert — no resolution workflow; every conflict row permanently unresolved for the execution gate — `implementation/services/calculations.py:226-240`
- §2.12 — insert — unnamed state preconditions → `ERR_INVALID_REQUEST` unless a substitute error is named — (e.g. `implementation/routes/sublicense.py:127-128`, `production.py:265-266`)
- §2.12 — insert — unknown route / unsupported method → `ERR_INVALID_REQUEST` (404/405) — `implementation/app.py:17-24`
- §3.1 — insert — package creation not gated on asset status; pool cap counts all packages ever created, overflow → `ERR_INVALID_REQUEST` — `implementation/routes/packages.py:44-60`
- §3.2 — insert — bar cascade defaults `OVERDUE` milestones and decrements `payment_delinquency_count` per each (floor 0) — `implementation/routes/broadcasters.py:121-128`
- §3.3 — insert — `parent_bid_id` validated for existence only (`ERR_BID_NOT_FOUND`); parent need not be `COUNTERED` or same-package — `implementation/routes/bids.py:89-95`
- §3.3 — insert — bid withdrawal performs no `X-User-ID` ownership check — `implementation/routes/bids.py:236-244`
- §3.3 — insert — `EXPIRED` is reserved; no transition reaches it — `implementation/services/system.py:71-72` (no writer anywhere)
- §3.3 — insert — accept response carries the newly created deal — `implementation/routes/bids.py:306`
- §3.4 — insert — `base_fee_cents` set equal to winning bid's `offered_fee_cents` — `implementation/routes/bids.py:285`
- §3.4 — insert — season count for `total_contracted_fee_cents` uses the §2.10 whole-days/365 rule; commitment bp rounded half-up — `implementation/services/calculations.py:62-69`, `implementation/routes/deals.py:92-93`
- §3.4 — insert — `milestone_weight` > 0; `DEFAULTED` milestones excluded; remainder distributed only when weights sum exactly 1.0, cycling, negative remainders removed in same order; allocation re-runs at renewal exercise — `implementation/services/calculations.py:82-118`, `implementation/routes/payment_milestones.py:50-51`, `implementation/routes/renewals.py:164`
- §3.5 — insert — invoicing also runs the §2.4 clock transitions (past-due invoice lands `OVERDUE` in the same request) — `implementation/routes/payment_milestones.py:126-128`
- §3.5 — insert — days past due counted as UTC calendar-date difference — `implementation/routes/payment_milestones.py:160,188`
- §3.5 — insert — `DEFAULT_GRACE_DAYS` = 30; declare-default first finalizes `late_fee_cents` as of the declaration instant — `implementation/services/calculations.py:25`, `implementation/routes/payment_milestones.py:187-191`
- §3.6 — insert — `NO_SHOW_GRACE_HOURS` = 24 — `implementation/services/calculations.py:26`
- §3.7 — insert — filing a measurement does not require the event to be `DELIVERED`; only confirmation does — `implementation/routes/production.py:331-359` vs `407-415`
- §3.7 — insert — `LATE_GRACE_DAYS` = 14 — `implementation/services/calculations.py:28`
- §3.8 — insert — blackout checks scoped to blackout windows on the deal's asset (approve and revoke) — `implementation/routes/sublicense.py:134-136,178-181`
- §3.8 — insert — revoke `reason` optional; defaults to `TERMINATION`/`BLACKOUT`; when both causes hold, treated as termination and no conflict row written — `implementation/routes/sublicense.py:172-195`
- §3.8 — insert — blackout `reason` is required; `applies_to_sublicense_only` is informational only — `implementation/routes/sublicense.py:213-215`
- §3.9 — insert — `RENEWAL_WINDOW_DAYS` = 90; offer filing on non-`RENEWAL_OPEN` deal → `ERR_DEAL_NOT_ACTIVE` — `implementation/services/calculations.py:22`, `implementation/routes/renewals.py:38-39`
- §3.9 — insert — `MATCHING_WINDOW_DAYS` = 30; offer `offered_fee_cents` ≥ 0 — `implementation/services/calculations.py:23`, `implementation/routes/renewals.py:45,55`
- §3.9 — insert — match/withdraw identity mismatch → `ERR_INSUFFICIENT_PERMISSIONS` (403) — `implementation/routes/renewals.py:120-121,175-176`
- §3.9 — insert — exercise on non-`RENEWAL_OPEN` deal → `ERR_DEAL_NOT_ACTIVE`; exercise resets deal `escalator_rate_pct` from the offer; extension = 3 × 365 = 1095 days; `FROZEN_GRACE_DAYS` = 30; breach cascade does not adjust `payment_delinquency_count` — `implementation/routes/renewals.py:135-136,156-158`, `implementation/services/calculations.py:27`, `implementation/routes/deals.py:126-136`

### Mismatch-revisions (PRD said X → revised to impl's Y)

- §3.4 — revise — dropped "the term must cover at least one full season" (impl enforces only `term_start < term_end`) — `implementation/routes/deals.py:66-67`
- §3.4 — revise — "weights must sum to exactly 1.0" softened: expected but never validated — `implementation/services/calculations.py:97-113`
- §3.6 — revise — `event_code` "unique within the deal" → uniqueness not enforced — `implementation/routes/production.py:200`
- §3.6 — revise — `credit_settled_cents` "rises as offset" → no operation ever increases it (full offset only when credit is zero) — `implementation/routes/production.py:158,175`
- §3.8 — revise — sublicense window "strict subset" → inclusive containment (`window_start` ≤ req start, req end ≤ `window_end`) — `implementation/routes/sublicense.py:139-140`
- §3.8 — revise — approval league-share "accrues" → derivable from stored fields, no accrual persisted — `implementation/routes/sublicense.py:151-152`
- §3.8 — revise — revoke cause "terminated state" → only `TERMINATED_BREACH`/`TERMINATED_CONVENIENCE` (not `RENEWED`/`LAPSED`) — `implementation/routes/sublicense.py:176`
- §3.9 — revise — exercise no longer "auto-creates fresh payment milestone and production obligation rows"; instead escalator reset + allocation/fee recompute are specified — `implementation/routes/renewals.py:152-165`

Notable verified alignments left untouched: the full error catalog (all HTTP codes match `implementation/errors.py`), every endpoint path+role in §4, the escalated-fee formula, make-good credit formula, posture ladder, suspension/bar cascades, and all clock-driven transitions.

## PIPELINE COMPLETE — 2026-08-13T15:05:00.000Z

All 9 steps done. 55/55 tests passing across 8/8 parallel rounds under per-test-server isolation.

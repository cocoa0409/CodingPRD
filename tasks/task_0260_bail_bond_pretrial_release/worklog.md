# Worklog — task_0260_bail_bond_pretrial_release

## Step 1: Create Task Directory — 2026-06-09T04:36:13.000Z

Created `tasks/task_0260_bail_bond_pretrial_release/` and `tasks/task_0260_bail_bond_pretrial_release/workspace/` via mkdir -p (pre-allocated index, no ./tasks/ scan). Verified `./INSTRUCTION.md` exists in project root for Step 3 copy.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-09T04:59:39.000Z

All three files written, parse cleanly, pass `scaffold_lint.py` with `VERDICT: clean lint`.

Generated a complete **Expert-difficulty** scaffold for **Bail Bond & Pretrial Release**. Generated purely from the scenario + spec without consulting any sibling task.

**Complexity profile:** Compliance/audit primary archetype, Ledger-reconciliation secondary; graph topology; cyclic + parallel-dimension state shapes; segregation-of-duties role model; layers = cascading side effects, dual-variant calc, rate/threshold triggers, optimistic concurrency, derived-field reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities** — Defendant, BailOrder, Bond, Indemnitor, IndemnityAgreement, CollateralItem, CourtDate, Notification, CheckIn, GpsDevice, ForfeitureProceeding, LedgerEntry (13 FKs, all with reverse-reachability GETs).
- **6 state machines** — Bond (parallel coverage_status × settlement_status), CourtDate, ForfeitureProceeding (cyclic FORFEITED→RECOVERY_OPEN→REINSTATED→re-FTA), GpsDevice (TAMPER loop), CollateralItem, IndemnityAgreement (branching).
- **14 calculations** — surety_premium (marginal tiered banding), required_collateral, collateral_held, collateral_refund, earned_premium (dual-variant), judgment_amount (dual-variant), remission_credit, compliance_score (joint-input weighting), defendant_active_exposure, indemnitor_exposure, notification_lead, grace_deadline, docket_overlap_check (buffered closed-interval), device_occupancy_check (aggregate-capacity-1).
- **22 validations** (priority-ordered), **47 endpoints** (incl. reverse-reachability GETs + `/_clock/set_current_utc` test-driving endpoint), **22 errors** (all triggerable), **5 roles** (BondsAgent, Court, ComplianceOfficer, RecoveryAgent, SystemAdmin), **1 OCC concurrency rule** (judgment-stale-bond on Bond.version).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** All 9 difficulty rules × 2 instances = **18 instances**, each with falsifiable distinguishing_aspect, structured setup_api_calls chains, and literal-pinned asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **36 active corner instances + 4 excluded_because stubs** across all 9 claim-extraction sections.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (423 calls scanned). File sizes: SCAFFOLD.yaml 1660 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1077 lines, SCAFFOLD_CORNER_DESIGN.yaml 1326 lines.

## Step 3: Copy Shared Files — 2026-06-09T04:59:39.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0260_bail_bond_pretrial_release/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-09T05:09:07.000Z

Generated `workspace/PRD.md` (269 lines, 47011 bytes) — a prose PRD for the Bail Bond & Pretrial Release API. Read SCAFFOLD.yaml only; both design files withheld.

**Structure**
- §1 Introduction — compliance/audit + ledger-reconciliation dual archetype.
- §2 Global Specifications (10 subsections): RBAC, fixed response envelope, pagination, common resource props/audit fields, nested retrieval & existence ordering, request validation ordering, monetary precision, cascading state & derived-field reconciliation, OCC on judgment, financial ledger.
- §3 Business Logic (9 subsections by lifecycle): onboarding, posting & activation, indemnitors & credit exposure, collateral, court-date docket, forfeiture/recovery/judgment, exoneration, GPS & check-ins, test clock.
- §4 47-endpoint table. §5 22-error table.

**Coverage:** all 13 entities (common_fields:false ones — Notification, CheckIn, LedgerEntry — explicitly noted to lack updated_at/version); all 12 calculations as precise prose (marginal tiered surety_premium with band boundaries 1,000,000/5,000,000 cents, floors 1000/800/600 bps, ÷10,000, 10,000-cent min; required_collateral PR 0/CASH full/SURETY 10/25/50% by tier; collateral refund 2,500-cent fee; net judgment 50,000-cent recovery credit floored; remission; compliance weights 0/1/2/+3; notification lead ÷3600 floor; grace deadline 30 days; docket overlap 30-min buffer closed intervals; device occupancy capacity 1); all 6 state machines with FROM→TO arrows + preconditions paired to error IDs; OCC rule (expected_bond_version + ERR_STALE_VERSION/412 on judgment endpoint); all 22 validations narrated in priority order; all 22 error IDs in narrative.

**Hard Contract Reports:** Field coverage PASS (51/51 entity fields, 28/28 request bodies, 10/10 query params). Rule coverage PASS (22/22 validations, 1/1 OCC, all state transitions, 12/12 calculations, sibling-branch symmetry checked). Path purity PASS (§3 has 0 path/method tokens in 400 backtick tokens). §2.2 envelope byte-identical to source.

## Step 5: Generate Unit Tests — 2026-06-09T05:29:59.000Z

Generated complete test infrastructure + design-index-driven suite. Read SCAFFOLD + DIFFICULTY + CORNER + PRD.

**test_helpers/ (Stage 1) — 9 modules:** types.py (entity TypedDicts + enums; Notification/CheckIn/LedgerEntry omit updated_at/version), api_errors.py (22 error IDs + HTTP map), api_client.py (one method per endpoint, all 47 incl. _clock), constants.py (premium bands, coverage %, fees, grace days, compliance weights, buffers), test_users.py (opaque-identity headers for 5 roles + make_* builders; SoD comparison keyed on distinct BondsAgent/ComplianceOfficer user-ids), factories.py (input-only payload factories with auto-unique phones/case-numbers/serials), assertions.py (per-entity shape assertions + ledger helpers), fixtures.py (composite tiers: draft/active SURETY bond, forfeited/recovery-open/judgment-ready lifecycles, GPS assigned/active, clock-pinned), __init__.py.

**test_suite/ (Stage 2) — conftest + 11 test files, 72 test functions.**

**Coverage:** Queue A (Difficulty): all 18 instances translated, 2 tests each → 36 tests, 0 skipped. Queue B (Corner): all 36 non-stub instances translated, 1 test each → 36 tests, 0 skipped. The 4 excluded_because stubs (fta_cascade_to_forfeited, indemnitor_exposure_binding_only, grace_not_expired_judgment_rejected, segregation_same_user_exonerate) NOT translated (cross-refs resolve to real difficulty instances). Every instance had verbatim + uniquely-derivable PRD support.

**Verification:** all 72 tests collect under pytest; every docstring ends with exactly one valid Design: tag resolving to a real instance (0 C4 violations); every quoted PRD sentence verbatim in PRD.md; no skip/skipif/xfail; no scaffold/§/Table leakage; clean import + byte-compile. NOTE: suite validated for collection/citations/coverage only — not executed against a live implementation (runner's responsibility).

## Step 6: Generate Implementation — 2026-06-09T05:29:59.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`. Read INSTRUCTION + SCAFFOLD + PRD (concurrent with Step 5; could not see test_suite/).

**Files:** start.sh (guarded-install foreground launcher, executable), requirements.txt (Flask 3.0.3), app.py (blueprint registration, error handlers, 0.0.0.0:$PORT bind), db.py (in-memory store, UUID/timestamp/version helpers), clock.py (pinnable logical clock for /_clock/set_current_utc + ISO 8601 3-digit-ms), errors.py (ApiError + 22-entry error→HTTP map), response.py (exact success/error/list envelopes, pagination in meta), middleware.py (X-User-ID/X-User-Role auth, RBAC, body+pagination parsing), helpers.py (field validators, sort-by-created_at pagination), views.py (serialization stripping internal fields), lookup.py (left-to-right path-existence → ERR_NOT_FOUND), services/calculations.py (money/score/time formulas, Decimal + ROUND_HALF_UP), services/domain.py (derived-field recompute, bubble-up, transition cascades), routes/ (defendants, bonds, indemnitors+collateral, court_dates+check-ins, gps, forfeitures+ledger+clock).

**Storage:** pure in-memory dicts keyed by UUID, no seeding; every collection empty on boot. Mutable resources carry id/created_at/updated_at/version (version starts 1, bumps on every mutation incl. derived recompute); 3 append-only records carry only id/created_at.

**start.sh:** reads $PORT (default 10000), `exec python3 app.py` foreground, app.run(host=0.0.0.0, port=$PORT, threaded=True). Install guarded by `if ! python3 -c "import flask"`. Verified clean fresh-process boot, 200 within ~1s.

**Notable decisions:** validation ordering auth→role→path-existence→body-FK→structural→uniqueness→state→OCC→business (enter-judgment: state<OCC<grace, priorities 8<9<16); parallel bond dimensions (coverage_status independent of settlement_status; judgment leaves coverage=FORFEITED, settlement=JUDGMENT_ENTERED); marginal-tier premium (3 bands summed as cents*bps integers, single /10000, one ROUND_HALF_UP, floored at 10000-cent min); sequential net judgment (face − liquidated collateral, then −50000 recovery credit only if passed_recovery_open flag, floored 0); docket overlap (closed intervals ±30min buffer inclusive); device occupancy (point-in-time count capacity 1, no time arithmetic); SoD (activating BondsAgent X-User-ID stored hidden on bond, compared vs exonerating ComplianceOfficer X-User-ID); cascades bump every touched child version/updated_at + recompute exposures/collateral-held + bubble BailOrder/Defendant status. Verified with smoke suites (60+ assertions) — all pass.

## Step 7: Run Tests and Iterate — 2026-06-09T05:40:00.000Z

Clean exit. All 8 parallel rounds passed 72/72.

**Iterations run:** 2 (initial diagnostic sweep + one fix sweep, then a confirming clean sweep).

The initial 8-round sweep showed the same 4 tests failing in all 8 rounds (deterministic, not flaky): `test_correct_version_judgment_succeeds_and_bumps_version`, `test_grace_deadline_value_is_forfeit_plus_30_days`, `test_reinstate_at_exact_grace_deadline_succeeds`, `test_surety_premium_second_band_floor_distinct_from_flat`.

**Tests deleted:** None. All four failing tests passed STEP 1 (PRD verbatim-covers + uniquely-derivable).

**Fixes applied to test_helpers/** (STEP 2 fixture bugs — request inconsistent with PRD, impl correctly rejected):
- `test_helpers/fixtures.py`, `setup_draft_surety_bond`: auto-created indemnitor used fixed default `credit_limit_cents=5_000_000`, but the agreement pledged `liability_share_cents` equal to bond face. For a 6,000,000-cent bond the share exceeded the limit, so impl correctly returned `ERR_CREDIT_LIMIT_EXCEEDED` (PRD §3.3, required check, must not weaken). Fix: size cosigner's credit limit to `max(share, 5_000_000)`. (Unblocked `test_surety_premium_second_band_floor_distinct_from_flat`.)

**Fixes applied to test_suite/** (STEP 2 — self-inconsistent setup):
- `test_suite/test_06_boundaries_overlap_invariants.py`, `test_grace_deadline_value_is_forfeit_plus_30_days` and `test_reinstate_at_exact_grace_deadline_succeeds`: both overrode `fta_clock="2026-07-02T00:00:00Z"` but left default `court_date_utc="2026-07-02T09:00:00Z"`. FTA at 00:00 is before the 09:00 hearing, so PRD-faithful timing check (§3.5, FTA only "at or after" scheduled_utc) correctly returned `ERR_TIMING_VIOLATION`. Fix: aligned `court_date_utc` to `2026-07-02T00:00:00Z` (inclusive FTA at exact instant).

**Fixes applied to implementation/** (STEP 3 — PRD-required behavior, faithful test):
- `workspace/implementation/services/domain.py`, `enter_judgment` (+ `recompute_collateral_held` gained `touch=False`): function touched the bond twice (via recompute_collateral_held + settlement_status write), bumping `Bond.version` by 2 when collateral present. PRD §3.6 + SCAFFOLD state verbatim that entering judgment increments bond version by one. Fix: recompute held collateral without separate bond touch and consolidate judgment's bond mutations into a single `db.touch(bond)`, yielding exactly +1. (Unblocked `test_correct_version_judgment_succeeds_and_bumps_version`.)

**Final result:** 8/8 parallel rounds passed 72/72 with empty failure union. Temporary results.*.json cleaned up.

## Step 8: Finalize PRD — 2026-06-09T05:44:24.000Z

Produced `workspace/PRD_FINALIZED.md` (269 lines, 0% line-count delta — one line revised in place). NOT skipped (Step 7 had 1 impl fix + 1 test_helpers fix + 2 test_suite fixes).

**Change list (one bullet):**
- §3.6 (Forfeiture/Judgment) — revise — clarified that entering judgment increments Bond.version by exactly one *in net*: the collateral_held_cents recompute that liquidation triggers is folded into that single bump rather than adding a separate increment — implementation/services/domain.py:367 (recompute_collateral_held(bond, touch=False)) and :386 (single db.touch(bond)).

**Why only one edit (other 3 diff items required none):**
- test_surety_premium_second_band_floor_distinct_from_flat — STEP 2 fixture bug in test_helpers/ (cosigner credit_limit undersized). Impl correctly raised ERR_CREDIT_LIMIT_EXCEEDED per PRD §3.3 already verbatim. No PRD silence/mismatch.
- test_grace_deadline_value_is_forfeit_plus_30_days & test_reinstate_at_exact_grace_deadline_succeeds — STEP 2 self-inconsistent test_suite/ setup. Impl FTA-timing + grace deadline already match PRD §3.5/§3.6 verbatim. No edit.
- test_correct_version_judgment_succeeds_and_bumps_version — STEP 3 impl bug fix. PRD §3.6 already said "by one," but §2.8's general cascade-version rule created a plausible +2 read; the edit pins §3.6's "by one" as net total and folds collateral recompute into it, resolving §2.8↔§3.6 tension.

**Pre-edit search (NO-NEW-MISMATCH):** enumerated all recompute_collateral_held/collateral_held_cents bond-touching callsites — pledge_collateral (touch=True standalone), revoke_bond (touch=True, bond already touched → multiple bumps), exonerate_bond (touch=True, multiple bumps), enter_judgment (touch=False, the suppressed one). Scoped the no-separate-increment claim with "here"/"in this one operation" to avoid mis-describing revoke/exonerate (which legitimately touch the bond multiple times and are not version-pinned by PRD). §2.8 general rule left intact for all non-judgment paths.

## Step 9: Complete PRD — 2026-06-09T05:55:27.000Z

Produced `workspace/PRD_COMPLETED.md` by copying PRD_FINALIZED.md and applying 13 minimal in-paragraph edits. Walked entire implementation (routes, services/domain.py, services/calculations.py, middleware, helpers, lookup, views, db, clock).

**Line counts:** source PRD_FINALIZED.md = 269 lines / 47,480 chars; PRD_COMPLETED.md = 269 lines / 51,543 chars. Char delta +4,063. No lines added/removed; no new sections.

**Counts:** 11 ambiguity-pins, 2 mismatch-revisions.

**Per change:**
- §2.1 — insert — ambiguity — empty/blank X-User-ID and unrecognized role → ERR_UNAUTHENTICATED (401) not 403 — middleware.py:23-26
- §2.3 — insert — ambiguity — list sort uses id as secondary ascending tiebreaker on equal created_at — helpers.py:76
- §2.4 — insert — ambiguity — version begins at 1; updated_at equals created_at at creation — db.py:42-46
- §3.1 — insert — ambiguity — total_active_exposure_cents = sum of full bail_amount_cents of ACTIVE/FORFEITED bonds, no collateral reduction; zero-bond defendant stays ACTIVE — domain.py:52-53,62
- §3.1 — revise — mismatch — BailOrder.status OPEN while only DRAFT bonds, BONDED once any ACTIVE/FORFEITED, RESOLVED only when every bond terminal — domain.py:89-104
- §3.1 — revise — mismatch — condition_codes closed set {GPS,CURFEW,DRUG_TEST,NO_CONTACT}; non-array/out-of-set → ERR_INVALID_REQUEST — defendants.py:78-80
- §3.3 — insert — ambiguity — agreement on non-DRAFT bond → ERR_INVALID_STATE before credit-limit rule; BINDING+PENDING basis — indemnitors.py:64-71
- §3.4 — insert — ambiguity — pledge collateral to non-DRAFT bond → ERR_INVALID_STATE — indemnitors.py:130-131
- §3.5 — insert — ambiguity — scheduled_utc unparseable or at/before clock → ERR_INVALID_REQUEST before docket-overlap — court_dates.py:40-48
- §3.5 — insert — ambiguity — notify non-SCHEDULED date → ERR_INVALID_STATE before timing check — court_dates.py:106-111
- §3.5 — insert — ambiguity — record-FTA order (date-status → timing → linked-bond ACTIVE); non-ACTIVE bond → ERR_INVALID_STATE — court_dates.py:160-169
- §3.6 — insert — ambiguity — remission_pct int/float; absent/non-numeric (bool excluded) → ERR_INVALID_REQUEST, out-of-range → ERR_INVALID_REMISSION — forfeitures.py:91-97
- §3.7 — revise — mismatch — exoneration recomputes BailOrder.status (RESOLVED only if all sibling bonds terminal, else BONDED) — domain.py:273 → recompute_bail_order_status:89-104
- §3.8 — insert — ambiguity — GPS assign non-UNASSIGNED → ERR_INVALID_STATE before gates; activate/clear-tamper/return illegal-state errors + device-status-before-bond-status order — gps.py:64,101-105,116-117,128-129
- §3.8 — insert — ambiguity — check-in bond_id non-existent or owned by different defendant → ERR_FK_NOT_FOUND — court_dates.py:204-208
- §4 — insert — ambiguity — enumerated optional equality-match list filter query params; unrecognized params ignored — bonds.py:89-94, defendants.py:58-60, indemnitors.py:108-113, court_dates.py:82-84,237-239, forfeitures.py:112-114

**Already uniquely pinned (no change):** premium banding/rounding, required-collateral percentages, refund/recovery-credit/remission formulas, compliance weights, lead-hours floor, docket-overlap buffer math, OCC-before-grace ordering, single-version-bump on judgment, grace boundary comparisons, ledger entry types/signs, response envelope.

---

## Pipeline Complete — 2026-06-09T05:55:27.000Z

All 9 steps complete. Final deliverable: `workspace/PRD_COMPLETED.md` is the canonical contract; `workspace/implementation/` passes 72/72 tests across 8 parallel per-test-server isolation rounds.

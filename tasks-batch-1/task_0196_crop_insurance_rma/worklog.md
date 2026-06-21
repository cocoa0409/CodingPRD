# Worklog — task_0196_crop_insurance_rma

## Step 1: Create task directory — 2026-06-06T00:00:00.000Z

Created pre-allocated directory `tasks/task_0196_crop_insurance_rma/` with `workspace/` subdirectory. Step 1 auto-increment scan SKIPPED per orchestration parameters (index pre-allocated to avoid collision with 4 concurrent pipelines).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T00:00:00.000Z

The scaffold lints clean with exit code 0. All three artifacts are generated and validated. I generated the scaffold purely from the scenario description and the skill specification, without inspecting any sibling task.

## Summary

Generated three validated scaffold artifacts for **task_0196_crop_insurance_rma** (Crop Insurance / USDA RMA) at **Expert difficulty**.

**Files written** (all lint-clean, `VERDICT: clean lint`, exit 0):
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Complexity profile:** primary archetype ledger-reconciliation (Yield Protection vs Revenue Protection on identical losses) + secondary compliance/audit; flat topology; branching/cyclic state shape; segregation-of-duties role model; layers = dual-variant calc, rate/threshold triggers, cascading side effects, optimistic concurrency.

**Scaffold contents:**
- **Entities: 10** — CommodityProgram, Policy, CoverageElection, Unit, AcreageReport, LossClaim, PreventedPlantingClaim, AgentCommission, Producer, Agent.
- **State machines: 6** (CommodityProgram, Policy, CoverageElection, Unit, LossClaim with a cyclic DRAFT↔UNDER_REVIEW revision loop + approve/deny branch, PreventedPlantingClaim).
- **Calculations: 6** — yield_guarantee_and_liability, total_premium (pinned per-acre-then-sum rounding), subsidy_split (subsidy_factor lookup), yp_or_rp_indemnity (3 variants YP/RP/RP_HPE), prevented_planting_indemnity, agent_commission (tier keyed on the very total it scales). All test literals computed in code.
- **Validations: 13** (priority-ordered: auth → existence → invalid-request → OCC → state → segregation → adjuster-assignment → temporal/referential/constraint).
- **Endpoints: 43** (REST CRUD + action endpoints + FK reverse-reachability GETs + one `/_clock/set_current_utc` test-driving endpoint).
- **Errors: 18** (all referenced); **Roles: 3** (RmaAdmin opaque; Agent and LossAdjuster both entity_backed:Agent, segregated).
- **Concurrency rules: 2** OCC entries (Unit version on acreage-report; Policy version on election-void).

**Design instance counts:**
- §1.8 Difficulty: **18 instances** — exactly 2 per each of the 9 §0.5 rules, each with distinct differentiation.
- §1.9 Corner: **37 active instances + 2 `excluded_because` stubs** across all 9 claim-extraction-guide sections; both stubs resolve to named §1.8 instances. Total 528 setup/trigger calls all conform to §1.5; all grounds references resolve; all instance names unique across the union.

One mid-build correctness fix: the cross-entity election-void instance was reshaped to a two-unit election (only one reported) so the election legitimately stays ELECTED and the void precondition fires `ERR_ELECTION_ALREADY_REPORTED`.

## Step 3: Copy INSTRUCTION.md — 2026-06-06T00:00:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T00:00:00.000Z

Generated `workspace/PRD.md` — **262 lines** (39949 bytes).

**Sections covered:**
- **§1 Introduction** — framing the RMA crop-insurance domain via its two design tensions (dual-variant indemnity, segregation of duties + temporal/OCC gates).
- **§2 Global Specifications** — 10 subsections: RBAC with all three roles + identities (2.1), fixed response envelope (2.2), pagination (2.3), common resource properties incl. the two `common_fields: false` identity entities (2.4), hierarchical cascade/version semantics (2.5), monetary precision + round-half-up/round-per-unit-then-sum (2.6), OCC on the two guarded writes (2.7), nested-path + FK existence (2.8), explicit validation priority ordering (2.9), server clock (2.10).
- **§3 Business Logic** — 8 subsections: commodity programs, policies/producers/agents, coverage elections, premium/subsidy ledger, acreage + unit lifecycle, loss-claim adjustment workflow, YP/RP/RP_HPE dual-variant indemnity calc, prevented-planting + commissions. No HTTP methods/paths in §3.
- **§4 Endpoint table** — all 43 endpoints.
- **§5 Error catalogue** — all 18 error IDs.

**Hard Contracts — all PASS:** Contract 1 (53/53 field names), Contract 2 (all 18 errors + 29 state/enum values + both OCC rules + validation priority + all calc constants in prose), Contract 3 (§3 path purity — 0 paths/methods).

**Confirmation:** Neither design YAML was read, grepped, or referenced; no sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-06T00:00:00.000Z

Generated complete test infrastructure for `task_0196_crop_insurance_rma` purely from the four input files plus the unit-test-generator skill spec.

**test_helpers/ (9 files)** — `__init__.py` (barrel export), `types.py` (entity TypedDicts; identity entities Producer/Agent omit `updated_at`/`version`), `api_client.py` (one method per §4 endpoint), `api_errors.py` (ApiErrorId enum + HTTP-status map), `assertions.py` (per-entity + `assert_premium_conserved`), `factories.py` (input-only payload factories), `constants.py` (subsidy factors, rate multipliers, commission tiers, coverage levels), `test_users.py` (opaque RmaAdmin + per-instance `make_agent_headers`/`make_lossadjuster_headers` for the two entity_backed:Agent roles), `fixtures.py` (tiered composite setup chains).

**test_suite/ (conftest + 10 test files, 73 tests)**
- Queue A (Difficulty): **36 tests**, exactly 2 per each of the **18** difficulty instances (all 9 rules).
- Queue B (Corner): **37 tests**, 1 per each of the **37** non-stub corner instances.

**Instances skipped per the PRD-first filter: 0.** Every asserted rule (indemnity formulas, premium rounding order, subsidy table, commission tiers, cascades, OCC, segregation/assignment gates, temporal boundaries, conserved ledger) is verbatim-stated and uniquely-derivable in PRD §2–§3.

**Stubs correctly NOT translated (2):** `Corner/state_machines/cascade_policy_cancel_voids_elections_units_clawback` (owned by `Difficulty/transitive_cascade/cascade_policy_cancel_void_units_clawback_depth3`) and `Corner/validations/segregation_pp_approve_by_selling_agent_already_covered` (owned by `Difficulty/priority_pair_validation_conflict/priority_state_invalid_beats_segregation`). Both cross-references verified to resolve to real present queue-A instances.

**Verification:** all files byte-compile; every test has exactly one `Design:` tag resolving to a real source instance; no skip/skipif/xfail; no scaffold/§ references in code; every PRD citation carries a distinctive ≥8-word substring surviving a literal grep of PRD.md; every test_helpers import resolves.

## Step 6: Generate implementation — 2026-06-06T00:00:00.000Z

Built a complete Python + Flask implementation in `workspace/implementation/`.

**Files (22 source + launcher):** `start.sh`, `requirements.txt` (flask 3.0.3), `app.py` (entry, blueprint registration, ApiError→envelope handler, 404/405→ERR_NOT_FOUND), `db.py` (in-memory dicts, UUID/timestamp/seq helpers, server clock), `errors.py`, `response.py`, `middleware.py` (auth + role checks); `routes/` (identity, commodity_programs, policies, coverage_elections, units, acreage_reports, loss_claims, prevented_planting_claims, agent_commissions, clock); `services/` (common, calculations, ledger, transitions).

**Endpoints: all 43 from PRD §4** — identity (2), commodity programs (6), policies (6), coverage elections (5), units (4), acreage reports (3), loss claims (8), prevented-planting claims (6), agent commissions (2), clock (1).

**Storage/reset:** pure in-memory module-level dicts keyed by id in `db.py`; no SQLite/JSON/tmp/open()/seeding (grep-verified). Each start.sh invocation is a fresh `python3 app.py` process → all state resets on boot.

**start.sh contract:** reads `$PORT` (default 10000), binds `0.0.0.0` (lsof-confirmed), foreground via `exec python3 app.py`, guards pip install behind import check.

**Fidelity points:** PRD-prose ordering over scaffold priority (assigned-adjuster before segregation; PP-acres before unit-reported); round-per-unit-then-sum premium; subsidy/producer split conserved by subtraction; commission tier on finalized total; OCC on exactly two writes (ERR_STALE_VERSION 412, after invalid_request before state); single policy version bump per void/cancel, cascades bump each child independently.

## Step 7: Run tests and iterate — 2026-06-06T14:40:35.000Z

All clean. The task is complete — all 73 tests pass in all 8 parallel rounds.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (initial diagnostic + post-fix verification). Final sweep: 73/73 passing in all 8 rounds, zero failures, zero flakiness.

**Root-cause note on the diagnosis:** The initial failures were deterministic (5 tests, same in all 8 rounds), but one (`test_loss_indemnity_differs_from_prevented_planting_indemnity`) presented as a Heisenbug — it passed in isolation and whenever instrumented, which sent me down several dead ends (stale-server, two-server-on-one-port, connection-reuse races — all disproven by tracing: single PID, fresh state, fresh-session-per-request still failed). The actual cause was that the error string `"Claim is not in UNDER_REVIEW status"` originates from the **prevented-planting** approve route, not the loss-claim route (which says `"Loss claim is not in UNDER_REVIEW status"`). The failing call was the PP-claim approve, not the loss-claim approve. No race existed; all 5 were deterministic test-setup bugs.

**Tests deleted:** None. Every failing test's underlying rule was verbatim-covered and uniquely derivable from PRD; all five were test-setup bugs fixable into PRD-faithful form.

**Fixes applied to `test_suite/` (all STEP 2 test-setup corrections):**
- `test_04_indemnity_calculations.py` — `test_loss_indemnity_differs_from_prevented_planting_indemnity`: reordered so the PP claim is created+submitted *before* the loss claim is approved. PRD §3.6 settles a unit to SETTLED only when no other claim on it is DRAFT/UNDER_REVIEW; the old order approved the loss claim first, which settled the shared unit and closed it, so the subsequent PP submit/approve failed.
- `test_02_state_machine.py` — `test_cancel_policy_with_approved_claim_rejected`: activate the policy *before* reporting the unit. PRD §3.2 requires an ELECTED election to activate, but accepting the sole unit's report bubbles the election ELECTED→REPORTED (PRD §3.5), leaving nothing to activate. Switched from `setup_reported_unit` to `setup_election_with_unit` + explicit activate + report.
- `test_08_acreage_and_temporal.py` — `test_insured_acres_conserved_after_report_supersede` and `test_unit_planted_acres_reflect_latest_accepted_report`: switched from a single-unit election to a two-unit election. With one unit, report A bubbles the election to REPORTED, so the superseding report B is rejected (PRD §3.5 requires the owning election be ELECTED). With a second PENDING unit the election stays ELECTED, so supersession on unit1 is permitted; the asserted invariants (`total_insured_acres == 100`, `planted_acres == 100`) are unchanged.
- `test_09_concurrency_and_void.py` — `test_election_void_blocked_by_reported_unit`: read the policy version *after* adding units (each add bumps the policy version via ledger recompute, PRD §3.4) instead of before. The stale pre-add version tripped the OCC check (ERR_STALE_VERSION), which PRD §2.7 evaluates before the already-reported gate this test targets.

**Fixes applied to `test_helpers/`:** None (the fixtures were correct; the bugs were in how individual tests sequenced/ordered the helper calls).

**Fixes applied to `implementation/`:** None. All speculative implementation changes made during diagnosis (a port-exclusivity wait, a Connection:close hook, a PID debug header, inline status-debug strings) were reverted; the implementation is byte-for-byte its original PRD-faithful form. No PRD-required check was weakened.

## Step 8: Finalize PRD — 2026-06-06T14:44:23.000Z

The edit is in place. Exactly one sentence revised in §3.5; line count unchanged at 261.

## Summary

**Line counts:** PRD.md = 261 lines; PRD_FINALIZED.md = 261 lines; delta = 0 lines (0%, one in-place sentence revision in §3.5).

**Changes (one bullet per edit):**
- §3.5 — revise — Widened the acreage-report "owning election must be `ELECTED`" precondition from "for a report to move the unit forward" to apply to **every** filing (including a superseding report on an already-`REPORTED` unit), and named the rejection error `ERR_INVALID_STATE` (impl: `workspace/implementation/routes/acreage_reports.py:50-52`).

**Of the four Step 7 items, only one required a PRD edit; the other three were pure test-setup/ordering bugs whose underlying rules are already verbatim-pinned in PRD.md:**
- Item 1 (test_04, loss vs PP indemnity): settle-only-when-no-DRAFT/UNDER_REVIEW-claim is fully pinned by §3.5 line 160 and §3.6. No edit.
- Item 2 (test_02, cancel with approved claim): activation-requires-ELECTED (§3.2 line 130) and single-unit report bubbling election ELECTED→REPORTED (§3.5 line 158) are both verbatim. No edit.
- Item 4 (test_09, void OCC ordering): OCC-before-business-rule is pinned by §2.7 + §2.9; unit-add bumps policy version by §3.4 + §2.5. No edit.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject identified: the ELECTED-election state gate enforced on acreage-report filing, and the error it returns.
- (b) Impl paths enumerated and read/grepped:
  - `routes/acreage_reports.py` `create_report` — the sole acreage-report POST endpoint; gate at lines 50-52 (`if election["status"] != "ELECTED": raise ERR_INVALID_STATE`), unconditional on every filing, evaluated after OCC (41-43) and before the deadline (58) and over-report (63) business rules.
  - `routes/acreage_reports.py:73-95` — supersession + unit PENDING→REPORTED + bubble, all gated behind the ELECTED check.
  - `services/transitions.py:33-42` `bubble_election_to_reported` — only ever fires from `ELECTED`; consistent with the gate.
  - Grep confirmed no other route file creates acreage reports; `ERR_INVALID_STATE` is the only error this gate raises and is in the §5 catalogue (HTTP 409).
- (c) Wording adjustment: widened scope to "any acreage report … for every filing (including … supersede …)" and softened the relative-order claim to a generic "state-machine precondition" rather than asserting a position relative to the deadline/arithmetic gates, so the sentence stays consistent with §2.9's global state-check-before-business-rules ordering that the impl follows, and with every election status (REPORTED/INDEMNIFIED/VOID) the gate rejects.

## Step 9: Complete PRD — 2026-06-06T14:51:01.000Z

All constants (subsidy table, plan multipliers, commission tiers, rounding orders) in the PRD match the implementation exactly — no changes needed there. My four edits are complete and minimal.

## Summary

**Source vs completed:**
- `PRD_FINALIZED.md`: 261 lines, 40319 chars
- `PRD_COMPLETED.md`: 261 lines, 41655 chars (char delta **+1336**; all edits are in-paragraph, no line count change, no new sections)

**Counts:** ambiguity-pins: **3**, mismatch-revisions: **1**

**Changes:**
- §2.3 Pagination — insert — ambiguity — Pinned the optional foreign-key list filters the impl supports per endpoint (`crop_code`/`county_code`/`crop_year`, `producer_id`/`agent_id`, `policy_id`/`commodity_program_id`, `coverage_election_id`, `unit_id`, `assigned_adjuster_id`, `agent_id`), exact-string match, unknown params ignored — `routes/commodity_programs.py:76`, `routes/policies.py:63`, `routes/coverage_elections.py:85`, `routes/units.py:70`, `routes/acreage_reports.py:122`, `routes/loss_claims.py:75`, `routes/prevented_planting_claims.py:71`, `routes/agent_commissions.py:28`
- §3.1 Configuring Commodity Programs — insert — ambiguity — Pinned that publish-harvest-price requires only that `harvest_price` be a number (no positivity/upper-bound check) and carries no program-status precondition (accepted in DRAFT/OPEN/CLOSED) — `routes/commodity_programs.py:126-136`
- §3.2 Policies (cancel cascade) — revise — mismatch — PRD said each voided election "voids its non-`SETTLED` units"; impl `void_election` only transitions `PENDING` units to `VOID`, leaving REPORTED/ACTIVE/SETTLED/VOID untouched (also internally contradicted §3.3's "still PENDING"). Revised to match impl — `services/transitions.py:63-67`
- §3.5 Acreage Reporting / Unit Lifecycle (unit creation) — insert — ambiguity — Pinned that adding a unit is not gated on the owning election's status; once the `coverage_election_id` resolves, the unit is created regardless of election state — `routes/units.py:19-53`

**Verified already-pinned (no change):** subsidy-factor table, plan-loading multipliers, commission tiers and boundaries, rounding orders (round-per-unit-then-sum, per-acre-first), dual-variant indemnity (RP=max(projected,harvest), RP_HPE=projected, calculated revenue always harvest), validation ordering, OCC on the two guarded writes, segregation/assigned-adjuster ordering, PP-claim segregation-only (no assigned-adjuster), `late_planted` semantics (null→false covered by "false otherwise"), single policy-version bump on cancel, and response envelopes including the empty-`{}` clock response.

# Worklog — task_0552_pool_construction

## Step 1: Create Task Directory — 2026-07-04T15:59:14.000Z

Task directory pre-created and reserved: `tasks/task_0552_pool_construction` (ID contention avoidance; auto-scan skipped per instructions). Ensured `workspace/` subdirectory exists. Scenario: Pool Construction & Remodel (design/3D & permit, excavation→steel→plumbing→gunite→plaster phase gates, equipment & feature selection, progress-draw schedule, subcontractor coordination, inspection milestones, startup & owner orientation, warranty/punch). Design difficulty: Expert (scaffold-generator only).

## Step 2: Generate Scaffold (Expert) — 2026-07-04T16:52:01.000Z

All three artifacts are generated, parse cleanly, honor the file-split rule, and pass `scaffold_lint.py` with a clean verdict.

Generated a fresh **Expert-tier** scaffold for scenario 552 (Pool Construction & Remodel). Built purely from the scenario + skill spec; no sibling tasks were consulted.

**Design DNA:** primary archetype *posture-driven gating* + secondary *workflow orchestration*; **flat entity topology** under `api_prefix: /pool-build`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; role model = peer_roles; immediate consistency.

**§1.1 Entities (9):** PoolProject, DesignPlan, PhaseGate, Inspection, Subcontractor, CrewAssignment, ChangeOrder, DrawRequest, PunchItem. All FKs use the canonical `FK -> Entity.id` prefix; each has reverse-reachability GETs.

**§1.2 State machines (11 blocks):** posture_driven PoolProject (construction lifecycle + derived `posture` OPEN/HOLD/STOP_WORK), cyclic DesignPlan `status` revision loop + parallel `permit_status` dimension, PhaseGate pipeline with FAILED→IN_PROGRESS rework, branching Inspection fork, Subcontractor ACTIVE↔SUSPENDED, ChangeOrder branch+apply/reverse compensation, DrawRequest, CrewAssignment, PunchItem. **1 concurrency rule** (OCC `draw-create-stale-project` on `PoolProject.version`).

**§1.3 Calculations (8):** draw_eligibility (dual-variant provisional/final), retainage_computation (per-line rounding), change_order_discount (tiered, pinned evaluation order), subcontractor_reliability (dual-variant projected/realized), draw_ledger + committed_crew_hours (conserved-quantity invariants), design_status_rollup, phase_progression, posture_derivation.

**§1.4 Validations:** 15 priority tiers (auth→authz→existence→field→state→OCC→safety/posture→temporal overlap→referential→uniqueness→fiscal).

**§1.5 Endpoints (35):** flat CRUD + consolidated transition endpoints + `/_clock/set_current_utc` (default `2026-05-01T00:00:00Z`).

**§1.6 Errors (25):** every one triggerable by a §1.8 or §1.9 test.

**§1.7 Roles (5):** BuilderPM/Designer/Owner/Inspector (opaque), Subcontractor (entity_backed).

**§1.8 difficulty design:** 9 rules, **19 instances** (dual_variant 2, combinatorial 3 across modes a/b/c, non_linear 2, transitive_cascade 2 [depth-3 + depth-2], priority_conflict 2, boundary_precision 2, cross_entity 2, temporal_overlap 2, compensating_invariant 2), each with executable setup_api_calls chains and code-computed literal asserts.

**§1.9 corner design:** 9 sections, **27 active instances + 16 exclusion stubs** (43 total) covering creation/not-found/required-fields/type/FK integrity, initial-state/invalid-transition/terminal-lockdown/precondition guards, priority conflicts, RBAC role+ownership denials, unauthenticated, pagination envelope, and OCC stale + version-bump.

**Validation:** `scaffold_lint.py` → `VERDICT: clean lint` (435 calls scanned, 0 violations). Verified: no forbidden concurrency vocabulary, no dangling grounds refs, unique instance names across §1.8∪§1.9, all stub `difficulty_instance` refs resolve, enum closure, and top-level key isolation across the three files. Files: SCAFFOLD.yaml 1222 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 694 lines, SCAFFOLD_CORNER_DESIGN.yaml 720 lines.

Note: endpoint count is 35 (slightly above the 20–32 Expert guideline band) because the scenario spans nine distinct real workflows; transitions were consolidated into per-entity action endpoints to hold the count down while keeping RBAC and reverse-reachability honest.

## Step 3: Copy INSTRUCTION.md — 2026-07-04T16:52:01.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0552_pool_construction/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T17:03:23.000Z

All three hard contracts pass. Contract 1: 61 field names, 0 missing. Contract 2 spot-check: all 25 error IDs surface in the §2/§3/§4 narrative (not just the §5 table). Contract 3: §3 has zero path/method leaks. The PRD is complete.

**Output written:** `workspace/PRD.md` (~284 lines).

**Section structure:** §1 Introduction; §2 Global Specifications (2.1 Actors/Auth/RBAC, 2.2 API Response Structure, 2.3 Pagination & reverse-reachability list filtering, 2.4 Common properties & versioning, 2.5 OCC on the project ledger, 2.6 Request validation order (12-step precedence), 2.7 The project posture gate, 2.8 Ledger conservation & numeric precision, 2.9 The logical clock); §3 Business Logic (3.1 Project intake/ledger init, 3.2 Design rendering & permit track, 3.3 Phase gates & pipeline, 3.4 Inspection milestones, 3.5 Subcontractor roster & crew coordination, 3.6 Change orders & volume discounts, 3.7 Progress draws/retainage/disbursement, 3.8 Startup/orientation/warranty closeout); §4 Endpoint Definitions (35 endpoints); §5 Error Code Catalogue (25 errors).

**Documented content:** Entities (9): PoolProject, DesignPlan, PhaseGate, Inspection, Subcontractor, CrewAssignment, ChangeOrder, DrawRequest, PunchItem. State machines (9) incl. PoolProject.construction_status + derived posture gate, DesignPlan.status cyclic loop + parallel permit_status, PhaseGate FAILED→IN_PROGRESS rework, Inspection branching fork, ChangeOrder apply/reverse compensation. Calculations (9): draw_eligibility (dual provisional/final), retainage (per-line rounding), change_order_discount (pinned-order tiered: 10% retainage, 500k/1.5M-cent tiers at 0/3/5%, completion factors 0.5/0.8/1.0, 24h cure buffer, default score 100), subcontractor_reliability (dual projected/realized), draw_ledger, committed_crew_hours, design_status_rollup, phase_progression, posture_derivation. Endpoints (35) incl. `/_clock/set_current_utc`. Errors (25). Roles (5): BuilderPM, Designer, Owner, Inspector, Subcontractor (entity_backed vs opaque distinction; Owner owner_user_id ownership check).

Hard Contract reports: Field coverage 61/61 PASS; Rule coverage PASS; Path purity (§3) 478 tokens, 0 leaks PASS.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) nor SCAFFOLD_CORNER_DESIGN.yaml (§1.9) was read/grepped/referenced. No sibling task directories opened. Generated solely from this task's SCAFFOLD.yaml + doc-generator SKILL.md + fixed section-2.2-response-structure.md.

## Step 5: Generate Unit Tests — 2026-07-04T17:36:11.000Z

Generated complete test infrastructure for task_0552_pool_construction (Pool Construction & Remodel, Expert tier), translating exclusively from the two design indices.

**`test_helpers/` (Stage 1) — 9 files**: types.py (role enum, 12 status/enum vocabularies, 8 entity TypedDicts w/ common_fields), api_client.py (ApiClient w/ 35 endpoint methods), api_errors.py (25 errors + HTTP-status map), assertions.py (per-entity + assert_ledger_conservation), factories.py (9 payload factories), constants.py (completion factors, retainage pct, discount tiers, cure buffer, phase sequence), test_users.py (role headers; make_owner_headers/make_subcontractor_headers), fixtures.py (~40 composite setup helpers), __init__.py.

**`test_suite/` (Stage 2) — conftest + 10 domain test files** test_01…test_10.

**Totals: 65 test functions**, all collected clean, each carrying exactly one `Design:` tag.
- **Queue A (§1.8 Difficulty): 38 tests** — all 19 non-stub instances covered by exactly 2 tests each.
- **Queue B (§1.9 Corner): 27 tests** — all 27 non-stub instances covered by 1 test each. The 16 `excluded_because:` stubs were not translated.

**Verification:** 84 docstring citation fragments all match PRD.md verbatim; no ellipses, no skip/skipif/xfail, no scaffold/table leakage; test_helpers imports clean.

**Instances skipped by PRD-first filter: none** — all 19 + 27 non-stub instances passed both conditions.

**One PRD-first adjudication flagged:** queue-A `boundary_precision_check/draw_net_equals_remaining_inclusive_boundary` asserts `amount_remaining_cents == 0`, but PRD §2.8 conservation (`remaining = contract − disbursed − retainage_held = 90000 − 90000 − 10000`) uniquely derives **−10000** (YAML omits withheld retainage). Core inclusive-≤ claim IS PRD-derivable, so kept it (2 tests) asserting uniquely-derivable outcomes (status FUNDED, net_disbursed_cents==90000, eligible_cents==100000, retainage_cents==10000) and dropped only the non-derivable `amount_remaining==0` sub-assertion.

## Step 6: Generate Implementation — 2026-07-04T17:36:11.000Z

Generated a complete Python + Flask implementation of the Pool Construction & Remodel API in `workspace/implementation/`.

**Files:** app.py (single-module Flask app, ~1000 lines), start.sh (executable launcher), requirements.txt (Flask>=2.2).

**start.sh launch:** Reads $PORT (default 10000), binds 0.0.0.0, runs foreground via `exec python3 app.py` (threaded=True). Dependency install guarded so per-test reboots skip pip install.

**Storage:** In-memory only — module-level STORE dict of 9 sub-dicts keyed by UUID, plus global insertion sequence and logical-clock cell. No file/SQLite/JSON/tmp writes (grep-confirmed). Fresh boot returns total_count=0 for all collections. No data seeded/preloaded at startup.

**Entities & endpoints:** All 35 endpoints (9 resource groups + `/_clock/set_current_utc`). Subcontractors intentionally have no list endpoint (not in §4).

**State machines:** PoolProject.construction_status (NOT_STARTED→IN_CONSTRUCTION→STARTUP_READY→ORIENTED→CLOSED w/ retainage-release cascade on PLASTER pass); PoolProject.posture derived gate (STOP_WORK/HOLD/OPEN priority rules, rework exemption); DesignPlan.status (cyclic) + permit_status (parallel); PhaseGate (FAILED→IN_PROGRESS rework); Inspection (branching PASS/FAIL/CANCEL cascades); CrewAssignment; Subcontractor; ChangeOrder (apply/reverse compensation); DrawRequest; PunchItem.

**Calculations (Decimal, round-half-up):** draw_eligibility (provisional vs final via completion factors 0/0.5/0.8/1.0), retainage (10% per-line), change_order volume-discount tiers (0/3/5%, pinned eval order), draw_ledger (conserved: contract/disbursed/retainage_held/remaining), committed_crew_hours (2dp), dual reliability scores (projected vs realized, first-pass via inspection_attempts==1), current_phase, design_status rollup.

**Cross-cutting:** Response envelope (meta/response_type/data), pagination (limit/offset/total_count/has_more, default 10/max 100, created_at asc), X-User-Role/X-User-ID auth w/ Owner/Subcontractor ownership checks, RBAC per role, full 12-step validation precedence (§2.6), OCC on draw-create via expected_pool_project_version (412). Project version bumps only on 4 enumerated ledger writes.

**Verification:** Two smoke suites (~90 assertions) pass; state wipe on restart confirmed.

**Interpretation note:** PoolProject.version bumped only by the four ledger ops §2.5 enumerates (not construction_status transitions or derived-field recomputes), per §3.6/§3.7 explicit callouts while §3.8 does not.

## Step 7: Run Tests and Iterate — 2026-07-05T02:17:25.000Z

All 8 parallel rounds now pass with 65/65. The loop is complete.

**Iterations run:** 2 (initial sweep + one fix + confirming sweep).

**Diagnosis:** Across all 8 rounds of the initial sweep, exactly one test failed, deterministically (not flaky): `test_07_change_orders_and_discounts.py::test_reverse_decreases_contract_by_exact_applied_delta`, with `assert 0 == 600000` tripping on the first assertion `co["applied_delta_cents"] == 600000`.

Applying the diagnostic protocol:
- STEP 1 (coverage + unique-derivability): PASS. PRD §3.6 states applying a change "set[s] the applied delta … applied_delta_cents is price_delta_cents multiplied by one minus the discount rate," and §2.2 states modify operations "return the created or updated resource object in the data field." The 600000 outcome (600000 delta, cumulative base 0 → 0% tier) is uniquely derivable.
- STEP 2 (test-vs-PRD consistency): the failure was a **test-helper bug**, not an implementation bug. Direct reproduction against a live server confirmed the APPLY transition response correctly returns `applied_delta_cents: 600000` (and GET returns 600000, which is why every other change-order test passed). The fixture `setup_change_order_applied` in `test_helpers/fixtures.py` called `apply_change_order(co["id"])` but **discarded its return value**, so it returned the stale CREATE response (`status=PROPOSED`, `applied_delta_cents=0`) while its own docstring promised "A single change order APPLIED."

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `setup_change_order_applied()`: changed `apply_change_order(co["id"])` to `co = apply_change_order(co["id"])` so the fixture returns the actually-applied change order (with `applied_delta_cents` and `status=APPLIED` populated), matching its docstring and the PRD "return the updated resource" contract. The sibling test `test_reverse_conserves_contract_dollars` uses the same fixture but only reads `co["id"]`, so it was unaffected.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful; the APPLY handler (`app.py:1271-1293`) correctly computes and returns the applied delta.

**Tests deleted:** None. No test failed the PRD-coverage or unique-derivability checks.

**Final result:** 8/8 parallel rounds green, 65/65 tests each, no flakiness observed.

## Step 8: Finalize PRD — 2026-07-05T02:29:29.000Z

Analysis complete. The single Step 7 item is a pure test-helper fixture bug that reveals no PRD gap, so PRD_FINALIZED.md is a verbatim copy of PRD.md with zero edits.

**Line counts:** PRD.md = 283 lines; PRD_FINALIZED.md = 283 lines. **Delta: 0 lines (0.0%).** The two files are byte-for-byte identical (confirmed via `diff`).

**Changes made:** None. Zero PRD edits.

### Rationale (per Step 7 item)

The `<step_7_diff>` reports exactly one failing test across all 8 rounds: `test_07_change_orders_and_discounts.py::test_reverse_decreases_contract_by_exact_applied_delta`, and the diff itself diagnoses it as a **pure test-helper fixture bug**, not a PRD-silence or PRD-mismatch. The only fix was to `test_helpers/fixtures.py::setup_change_order_applied()` (capturing the return value of `apply_change_order`). No `implementation/` change, no test deletion, no `test_suite/` change was made.

Per the method ("Patch PRD_FINALIZED.md only when impl pinned a choice PRD left open — not every item is a PRD silence (some are pure fixture bugs)"), a pure fixture bug produces no PRD edit **provided** the behaviors it touched are already uniquely determined by the PRD. Verified both touched behaviors are fully PRD-determined and impl-faithful:

1. **Applied-delta computation** (fixture's `co["applied_delta_cents"]` should be 600000). PRD §3.6 uniquely determines this: single CO, cumulative pre-discount base = 0 (no prior APPLIED positive-delta COs), tier 0% (base < 500,000), `price_delta_cents` = 600000 > 0 → `applied_delta_cents` = round-half-up(600000 × (1 − 0)) = 600000. Matches `implementation/app.py:1274-1283` exactly.
2. **Transition returns the updated resource** (the fixture's real bug was discarding the APPLY response and reusing the stale CREATE response). PRD §2.2 ("operations that create or modify a resource will return the created or updated resource object in the data field") and §4 ("state-changing transitions return HTTP 200 with the affected resource") uniquely determine this. Matches `implementation/app.py:1311` (`return respond_object(serialize_change_order(c))`).

Both are PRD-determined and impl-faithful, so the fixture bug reveals neither silence nor mismatch. No edit warranted.

### Per-edit pre-edit search log

No edits were committed, so there is no per-edit search log. For completeness, the NO-NEW-MISMATCH enumeration performed for the *candidate* subject (then rejected as needing no edit):

- **(a) Subject identified:** change-order APPLY behavior — the `applied_delta_cents` volume-discount computation and the transition-response "return updated resource" contract.
- **(b) Impl paths enumerated / read:** `app.py:1244-1311` (`transition_change_order`, all four actions; APPLY 1271-1293 returns via `respond_object(serialize_change_order(c))` at 1311); `app.py:1236-1241` (`_discount_pct` tier thresholds 500,000 / 1,500,000); `app.py:1275-1277` (`cumulative_pre`); `app.py:279-281` (`project_applied_cos` APPLIED filter); `app.py:492-503` (`serialize_change_order`); `app.py:540-542` (`respond_object`); `app.py:119` (`rhu` round-half-up); REVERSE path 1295-1309 + contract roll-up + `bump_project_version` cascade cross-checked.
- **(c) Wording adjustment:** None — every enumerated path is already correctly and uniquely described by existing PRD §3.6 / §2.2 / §4 prose.

**Conclusion:** PRD_FINALIZED.md is an exact, unmodified copy of PRD.md.

## Step 9: Complete PRD — 2026-07-05T02:42:18.000Z

All edits applied. Line count is unchanged at 283 (every change was in-paragraph).

**Source vs completed**
- Source: `PRD_FINALIZED.md` — 283 lines, 44,047 chars (44,179 bytes)
- Completed: `PRD_COMPLETED.md` — 283 lines, 45,946 chars (46,087 bytes)
- Char delta: **+1,899 chars** (+1,908 bytes). Line count unchanged (all edits are in-paragraph inserts/revisions; no new paragraphs or sections).

**Counts**
- Ambiguity-pins: **4** (§2.1, §2.3, §3.2 jurisdiction, §3.2 permit_number), plus one sub-pin folded into the §2.9 revision (`to_iso8601` required/must-parse).
- Mismatch-revisions: **3** (§2.4, §2.6, §2.9).

**Per-change log**
- §2.1 — insert — ambiguity — Pinned that only `X-User-Role` governs authentication: a missing/empty `X-User-ID` does not itself cause `ERR_UNAUTHENTICATED`; it is consulted solely by the Owner/Subcontractor ownership checks, so its absence surfaces (if at all) as `ERR_FORBIDDEN`. (impl `require_auth` app.py:241-246; `check_owner` app.py:263-265; sub ownership app.py:1168)
- §2.4 — revise — mismatch — PRD's blanket "any mutation... incl. a recomputation of a derived field... increments version" over-predicted impl. Revised to: version advances only on a resource's own stored-field mutations; derived/computed fields (postures, ledger, `current_phase`/`design_status`, `committed_crew_hours`, reliability, `inspection_attempts`) are computed lazily on read and never bump version; and the `PoolProject` version advances only on the four ledger ops (draw create/fund, CO apply/reverse), while its `construction_status` lifecycle transitions bump `updated_at` only. (impl `touch`/`touch_project_meta`/`bump_project_version` app.py:157-172; lazy serialization app.py:405-420; construction_status bumps app.py:676,684,893,988)
- §2.3 — revise — ambiguity — Pinned that out-of-range `limit`/`offset` are clamped (not rejected), non-integer/unparseable values fall back to defaults, and `created_at` ties are broken by ascending creation (insertion) order. (impl `get_pagination` app.py:588-604; sort key `(created_at,_seq)` app.py:613)
- §2.6 — revise — mismatch — The precedence table grouped ownership with role-permission at step 2 (before existence), but impl evaluates the Owner/Subcontractor ownership check against the resolved target, i.e. after existence (step 3) though still before body validity (step 4); a non-existent target therefore yields 404, not 403. Role-permission still precedes existence. (impl `must_get` then `check_owner`: app.py:666-668, 1166-1169, 1438-1439)
- §2.9 — revise — mismatch (+ embedded ambiguity sub-pin) — The logical clock is write-only and read by no scheduling check; overlap/site-occupancy/cure-buffer are computed directly from the bookings' supplied `start_at`/`end_at` endpoints, never from wall-clock or the clock, so setting the clock changes no outcome. Also pinned `to_iso8601` as required and must parse as ISO 8601 (else `ERR_VALIDATION`). (impl temporal guards app.py:1058-1117; `set_clock` app.py:1495-1506; `LOGICAL_CLOCK` never read — only assigned at app.py:1505)
- §3.2 — revise — ambiguity — Pinned `jurisdiction` as optional on permit submit (recorded when supplied, else left null). (impl `opt_str` app.py:791-794)
- §3.2 — revise — ambiguity — Pinned `permit_number` as optional on permit issue (stamped when supplied, else remains null). (impl `opt_str` app.py:800-803)

**Notes on what was deliberately left unchanged (verified as already-pinned or immaterial):** all endpoint routes/roles, the full §2.6 error precedence for the remaining steps, posture derivation and its four/two-operation block sets, the design/permit and phase-gate/inspection state machines, the volume-discount schedule, draw eligibility/retainage/ledger conservation math (per-line rounding), reliability formulas, half-open interval + adjacency + 24h cure rules, and all response field shapes were checked field-by-field against `serialize_*` and match impl exactly. Absence-of-constraint items (e.g., `budget_cents`/`pool_gallons` not required to be positive; `scheduled_at` stored as an opaque string) were left silent since impl simply imposes no additional constraint, and §3.4's "every gate on the project" already correctly pins the STARTUP_READY trigger (so §3.8's "five gates" narrative was left intact).

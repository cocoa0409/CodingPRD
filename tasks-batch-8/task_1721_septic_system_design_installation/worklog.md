# Worklog — task_1721_septic_system_design_installation

## Step 1: Create Task Directory — 2026-08-14T11:12:33.000Z

Task directory `tasks/task_1721_septic_system_design_installation/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invocation. Step 1 treated as DONE per instructions; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T12:25:00.000Z

Generated SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 23 instances across all 9 Difficulty Rules), and SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 51 instances: 45 active + 6 excluded_because stubs) from the septic-installer scenario. scaffold_lint.py verdict: clean lint (132 endpoints, 19 entities, 1124 calls scanned). All formula-derived asserts pre-computed by executing the §1.3 formulas.

Verbatim subagent summary:

All four tasks complete. Final summary:

## Scaffold Generated — task_1721_septic_system_design_installation

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/`):
- `SCAFFOLD.yaml` (2,583 lines) — §1.0–§1.7, no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,708 lines) — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3,622 lines) — single top-level `scaffold_corner_design:`

**Surface counts (lint-verified):** 19 entities, 132 endpoints, 29 error codes, 9 calculation rules, 10 state machines, 30 validation rows, 3 OCC concurrency rules, 6 RBAC roles (5 entity-backed + PlatformAdmin opaque), 1,124 test-recipe calls scanned.

**Difficulty design (§1.8): 23 instances** — every §0.5 rule carries ≥2: dual_variant_calc 2 (design sizing book-vs-reduced with tank-leg asymmetry; RepairCase provisional-vs-final estimate across an amendment gap), combinatorial_formula 3 (single-terminal-ceil area rounding 352-vs-353 trap; contract-level proration 58333-vs-58331 trap; tank catalog step-up with exact-multiple boundary), non_linear_state_machine 2 (design reject-revise OCC cycle; permit suspend-reinstate × installation remediate decoupled cycles), transitive_cascade 3 (depth-3 approval→supersede→suspend→FAILED_HOLD; depth-3 final-pass→complete→finalize→education-armed; depth-2 clock→expire→FAILED_HOLD), priority_pair_validation_conflict 3 (state>temporal; safety>temporal; state>fiscal), boundary_precision_check 3 (science age 24-vs-25; money ceiling 506700 exact-vs-+1; permit inclusive expiry 5-vs-6), cross_entity_state_dependency 3, resource_temporal_overlap 2 (closed-window visit containment vs zero-width inspector capacity-per-period), compensating_invariant 2 (RECORDED-science singleton; APPROVED-design singleton).

**Corner design (§1.9): 51 instances** (45 active recipes + 6 `excluded_because` stubs) across all 9 taxonomy sections: entities 10, state_machines 7, calculations 4, validations 8, endpoints 2, errors 9, rbac 6, cross_cutting_layers 4, consistency_model 1.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint`. Beyond the linter, I ran (a) grounds resolvability against §1.1–§1.7 (zero dangling refs), (b) placeholder closure across all 68 active recipes (zero unbound `${var}`), (c) a full state-machine replay of all 1,124 calls simulating transitions/cascades/OCC (zero rule breaks), and (d) executed every formula-derived assert as Python — this caught and fixed two real bugs mid-design (a 352-vs-353 rounding trap that only discriminates at the 1-bedroom HWT fixture, and a rule-7 instance whose error pin had to move from `advance` to `remediate` because the suspend cascade relocates the from-state).

**Notable design decisions:** segregation-of-duties role model enforced by license/badge identity equality (designer≠approving officer, inspector≠crew lead, scientist void ownership); version-pinning of science records into designs with supersession cascades; per-site deterministic period clock (default 0) driving permit expiry, freeze windows, science staleness, and contract lapse — no wall-clock anywhere; tank-vs-absorption variant asymmetry (reduced-flow variance affects only the area leg); and a 42-endpoint flat alias read surface added to satisfy FK reverse-reachability for the deeply nested hierarchy.

## Step 3: Copy Shared Files — 2026-08-14T12:23:33.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1721_septic_system_design_installation/workspace/INSTRUCTION.md` (1,424 bytes). Verified all three scaffold artifacts exist (SCAFFOLD.yaml 125,567 B; SCAFFOLD_DIFFICULTY_DESIGN.yaml 164,710 B; SCAFFOLD_CORNER_DESIGN.yaml 221,577 B).

## Step 4: Generate PRD — 2026-08-14T12:40:49.000Z

Verbatim subagent summary:

PRD generation complete. All three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/workspace/PRD.md` — 382 lines (dense prose + a 132-row endpoint table and 29-row error catalogue).

**Sections produced:**
- **§1 Introduction** — 2 paragraphs (regulatory/business context + system scope, deterministic per-site clock, six segregated roles)
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (headers, 6 roles, per-role identity prose), 2.2 API Response Structure (**byte-identical** to the fixed verbatim block — verified programmatically), 2.3 Pagination & List Filtering (`limit` 10/1/100, `offset` 0, `created_at` ascending, `meta` fields, all filter params), 2.4 Resource Identity/Timestamps/Versioning, 2.5 Hierarchy, Path Validation & Flat Read Surface (all 17 path params named), 2.6 Logical Site Time & Seasonal Clock, 2.7 OCC (3 rules), 2.8 Cascading State Propagation, 2.9 Validation Order (all 29 priorities in explicit precedence prose)
- **§3 Business Logic** — 9 subsections (onboarding → soil science → design/sizing/amendment chain → authority review & variances → permits → installation/inspections/materials → freeze & closure → education/maintenance/visits → repair cases & replacement estimation); no paths or HTTP methods anywhere in §3
- **§4 Endpoint Definitions** — 4-column table, all 132 scaffold endpoints verified present (83 nested + 49 flat aliases)
- **§5 Error Code Catalogue** — 2-column table, all 29 errors with exact HTTP statuses

**Scaffold coverage audit:**

```
Contract 1 (Field-Name Coverage):
- entities[].fields + endpoint inputs + query params + path params: 108 required, 108 present, 0 missing — PASS

Contract 2 (Rule Coverage):
- validations[] priority ordering: 29 expressed in fixed-precedence prose (§2.9), 0 missing
- concurrency_rules[] OCC: 3/3 (expected_design_version / expected_permit_version / expected_contract_version + ERR_STALE_VERSION/412)
- state_machines[].transitions: 10 machines, all transitions with preconditions, error IDs, side effects
- calculations[]: 9/9 with constants embedded (150/120 gpd, 1.5 surcharge, 4 soil rates, 24-inch/1.25 shallow layer, 2.0-day retention, 9-size tank catalog, reserve fraction 1.0, 6-period inclusive permit window, 12-period proration year, strict->24 science age, 900¢/sqft ceiling with equality-passes boundary, 4200¢/gpd dual provisional/final estimate)
- cross-entity cascades: science supersession→DRAFT withdrawal; approval supersession→permit SUSPENDED→installation FAILED_HOLD; revoke→ABANDONED; completion→FINALIZED→education armed; lapse/expiry; cancel deletes future visits; reinstate no-auto-restore asymmetry
- all 29 error IDs appear in §2/§3; all 6 roles with identity prose; all state/enum values verbatim — PASS

Contract 3 (§3 Path Purity): 434 backticked tokens scanned, 0 path/method violations — PASS
```

**Note:** `LAPSE_GRACE_PERIODS` is referenced by the scaffold's contract-lapse transitions but has no numeric value defined anywhere in the scaffold; per the no-invention rule, the PRD expresses it only as "the lapse grace window" without a fabricated constant.

## Step 5: Generate Unit Tests — 2026-08-14T13:30:00.000Z

Verbatim subagent summary:

Done. Summary of the generated test infrastructure for `task_1721_septic_system_design_installation`:

## Counts

- **Queue A (Difficulty): 44 tests across 22 of 23 instances** — every covered instance has exactly 2 tests.
- **Queue B (Corner): 45 tests across all 45 non-stub instances** — 1 test each. The 6 `excluded_because:` stubs were not translated; their `difficulty_instance` cross-references all resolve.
- **Total: 89 tests**, all collected cleanly by pytest.

## Skips / partial translations (PRD-first filter)

1. **`Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_material_verify` — SKIPPED (0 tests).** The pinned scenario is verifying the same delivery twice, expecting `ERR_INVALID_STATE` to pre-empt the fiscal ceiling check. The PRD never states that re-verifying an already-verified delivery is rejected at all — §3.6 only describes the false→true flip. Two faithful readers could ship idempotent-200, 402 (budget re-counted), or 409; not uniquely derivable. Gap left as a gap.
2. **`Corner/state_machines/maintenance_contract_auto_lapse_and_expire_on_clock` — LAPSED leg only.** The PRD never states the lapse grace period count (scaffold-only `LAPSE_GRACE_PERIODS: 2`), so the EXPIRED-at-period-7 leg is not derivable; the test asserts only the PRD-pinned ACTIVE→LAPSED transition at end_period+1.
3. **`Difficulty/boundary_precision_check/permit_expiry_inclusive_window_boundary` — failure leg rerouted.** The instance's advance-at-period-6 leg contradicts the PRD: the clock advance first expires the permit and cascades both NOT_STARTED installations to FAILED_HOLD, so §2.9's fixed order (state(5) before permit-expiry(7)) yields `ERR_INVALID_STATE`, not the pinned `ERR_PERMIT_EXPIRED`. Translated as: (a) advance at exactly `expires_period` succeeds with `started_period == 5`; (b) the past-window `ERR_PERMIT_EXPIRED` is asserted via the reinstate path (PRD §3.5 names it verbatim), which the expiry cascade cannot pre-empt (SUSPENDED permits do not auto-expire).
4. **Initial-`version == 1` sub-assertions dropped** in two entity-creation corner tests (`create_installer_company_returns_201_with_all_fields`, `system_fields_on_create_...`) — §2.4 says version "increments by one on every mutation" but never pins the initial value. Core claims (server-minted bare-UUID id, ISO-8601 timestamps, 201 envelope, retrievability) kept; relative version increments (mutation bumps by exactly one) are still asserted elsewhere.
5. **`occ_stale_version_on_contract_renew`** needed one correction to the recipe's capture order: the clock-advance lapse is itself a mutation that bumps the contract version (§2.4), so the creation-time version is correctly stale post-lapse — the test asserts stale→412 first, then GETs the fresh version and asserts the successful renew (end 20, fee 210000, version+1).

## test_helpers/ produced (9 files)

`types.py` (19 TypedDicts, 16 enums), `api_client.py` (~100 endpoint methods covering nested + flat alias surface), `api_errors.py` (29 error IDs registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions), `factories.py` (input-only payload factories), `constants.py` (all PRD numeric constants), `test_users.py` (shared opaque-admin headers + per-entity `make_<role>_headers` builders for the 5 entity-backed roles), `fixtures.py` (tiered composites through `setup_completed_installation`, `setup_contract`, `setup_lapsed_contract`, `setup_open_repair_case`, plus hold-point walkers and leg-level helpers), `__init__.py` barrel.

## Self-check results

- **Stage 1**: all modules compile; `test_helpers` imports cleanly against the installed framework.
- **Stage 2**: all 89 tests have exactly one `Design:` tag as the final docstring line; every tag resolves to a real instance with matching rule_id/section; no test tags a stub; no `skip`/`skipif`/`xfail` anywhere; every ≥40-char quoted docstring span was programmatically verified as a verbatim substring of `workspace/PRD.md` (whitespace-normalized). `workspace/implementation/` was never read or written; no sibling task directories were touched.

Paths:
- `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/test_suite/`

## Step 6: Generate Implementation — 2026-08-14T13:30:00.000Z

Verbatim subagent summary:

All 132 scaffold-declared endpoints are registered (113 unique paths; 19 paths serve both POST and GET). Everything is done.

## Summary

**Files produced** in `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/workspace/implementation/`:

- `start.sh` — foreground launcher, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip
- `requirements.txt` — flask only
- `app.py` — app factory, ApiError/404/405/500 handlers emitting the scaffold error envelope, route registration, `main`
- `db.py` — in-memory `STORE` dicts (19 collections), UUID minting, ISO-8601 UTC timestamps with 3 fractional digits, `version`/`updated_at` mutation rule, insertion-sequence tiebreak for `created_at` sort. **Store starts empty; zero seeding.**
- `errors.py` — `ApiError` + all 29 error IDs with their HTTP statuses (incl. 402 budget, 412 OCC)
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`; defaults 10/0, clamped to [1,100])
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), body parser, typed field validators, 20-char narrative rule
- `helpers.py` — left-to-right path-chain resolvers (404), body-FK scope resolvers (422), query filters
- `services.py` — all calculations and cascades
- `routes_*.py` — 10 route modules covering companies, 5 staff registries, customers, sites, science, designs, permits, installations/inspections/materials, variances, contracts/visits, repair cases, education, and the full flat alias read surface

**Endpoints:** 132/132 from the scaffold's endpoint table (verified against the live URL map).

**State machines wired:** Site (freeze/unfreeze/close with open-work gate), SoilEvaluation + PercolationTest (auto-supersession + owner-only void + pinned-by-live-design refusal), SystemDesign (submit/decide/revise-with-OCC/withdraw + amendment chain + approval supersession), Permit (issue/suspend/reinstate-with-OCC/expire/revoke/finalize), Installation (4 gated advance legs, remediate, abandon, auto-complete/fail from FINAL), Inspection (pass/fail with maturity + crew independence), VarianceRequest, MaintenanceContract (lapse→expire via clock, renew-with-OCC, cancel deleting future visits), RepairCase (triage/begin/resolve/close, auto-resolve on replacement completion).

**Calculations wired (Decimal, per pinned rounding order):** daily flow (150/br + HWT ×1.5, round-half-up 1dp), absorption area (single final ceil; AREA_REDUCTION variant swaps 120 into the area leg only), tank catalog step-up (always book flow), reserve from post-ceil area, permit window `issued+6-1`, science expiry strict `>24`, material budget ceiling `area×900` strict `>`, proration rounded once, provisional/final replacement estimate `flow×4200`.

**Boot smoke test:** `start.sh` launched on a free port in foreground → 3 smoke suites passed against live boots: (1) full lifecycle + auth/envelope/pagination/404-chain checks, (2) deep cascade suite (approval supersession→permit suspend→FAILED_HOLD, freeze/thaw, science-age 24-vs-25 boundary, AREA_REDUCTION leg divergence, permit expiry cascade, replacement repair auto-resolve, scheduling conflict, crew SOD, revoke→ABANDONED, close gating, void SOD/pinning), (3) reinstate-with-OCC version bump, PUMP gate for PRESSURE_DISTRIBUTION, contract lapse→expire boundary, cancel deleting future visits, flat get-by-id surface. Fresh-boot check confirmed an empty store. All servers shut down after each run.

One scaffold gap to flag: `LAPSE_GRACE_PERIODS` is referenced symbolically in SCAFFOLD.yaml/PRD.md but never assigned a numeric value; I pinned it to `3` as a single named constant in `constants.py` (one-line change if the test suite expects a different value).

## Step 7: Test–Fix Iteration Loop — 2026-08-14T14:05:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 89 tests/round).

**Iteration 1:** 87/89 in all 8 rounds — two deterministic failures (no flakiness):
1. `test_action_endpoint_conditional_pump_gate` (test_07) — asserted advance blocks with ZERO PUMP deliveries. PRD §3.6 states the universal rule "every `PUMP` delivery must be verified" (contrasted with the existential hold-point phrasing "requires a passed hold-point inspection"); zero-delivery blocking is not uniquely derivable. Per STEP 1c/STEP 2 the test was edited, not deleted: it now delivers an UNVERIFIED PUMP (blocks with `ERR_MATERIALS_UNVERIFIED` — verbatim PRD), then verifies it and advances (both covered assertions kept; GRAVITY no-pump-requirement leg unchanged).
2. `test_final_estimate_reads_issuance_pinned_amended_design` (test_09) — `begin_remediation` returned `ERR_REMEDIATION_NOT_STARTED` when the permit pinned an AMENDMENT of the triage-time design. Implementation bug (STEP 3): §3.9's final-estimate sentence ("amended between triage and issuance") is unreachable under literal row equality, so the remediation gate and the completion auto-resolve must follow the §3.3 amendment chain. Added `design_descends_from()` to services.py and used it in `routes_repairs.begin_remediation` and `services.complete_installation`.

**Iteration 2 (verification sweep):** 89/89 in all 8 rounds. Union of failures: empty. No tests deleted; no test_helpers changes.

## Step 7: Run Tests and Iterate — 2026-08-14T13:40:00.000Z

Verbatim subagent summary:

Exit condition met — clean 8-round parallel sweep. Summary:

## Summary

**Iterations run:** 2 (initial sweep + verification sweep after fixes). Final state: **89/89 passed in all 8 concurrent rounds, zero failures in the union.**

**Tests deleted:** none. Both failures resolved without deletion — one via a STEP 1c/STEP 2 test edit, one via a STEP 3 implementation fix.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/test_suite/test_07_inspections_and_materials.py` — `test_action_endpoint_conditional_pump_gate`: the original asserted that advancing to `READY_FOR_FINAL` on a PRESSURE_DISTRIBUTION design with **zero** PUMP deliveries fails with `ERR_MATERIALS_UNVERIFIED`. PRD §3.6 states the universal rule *"every `PUMP` delivery must be verified"* (and deliberately contrasts it with the existential hold-point phrasing *"requires a passed hold-point inspection"*), so zero-delivery blocking is not uniquely derivable — two faithful readers diverge (vacuous-truth forall vs. existence-required). Edited the test to exercise the verbatim-covered rule instead: an **unverified** PUMP delivery blocks the leg with `ERR_MATERIALS_UNVERIFIED`; verifying it unblocks the advance. The PRD-covered GRAVITY-carries-no-pump-requirement leg is unchanged. Removed the now-unused `deliver_and_verify_material` import.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/workspace/implementation/services.py` — added `design_descends_from(design, ancestor_id)` (walks the §3.3 `supersedes_design_id` amendment chain); `complete_installation` now matches replacement repair cases chain-aware instead of literal `replacement_design_id == permit.design_id`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/workspace/implementation/routes_repairs.py` — `begin_remediation` gate now accepts an installation whose permit pins the case's replacement design **or a descendant amendment of it**. Rationale (STEP 3): §3.9's final-estimate sentence (*"the flow of the design row pinned at permit issuance, which may differ from the provisional figure whenever the replacement plan was amended between triage and issuance"*) is unreachable under literal row equality — after amendment, the triage-time design is SUPERSEDED and no permit can pin it (issuance requires APPROVED) — so the whole-section-consistent reading uniquely requires chain-aware matching.

**No flakiness observed:** both failures were deterministic (8/8 rounds) in iteration 1; the fix held deterministically (8/8 rounds) in iteration 2.

## Step 8: Finalize PRD — 2026-08-14T13:50:00.000Z

Verbatim subagent summary:

Done. PRD_FINALIZED.md is written with a minimal, two-paragraph patch scoped exactly to the step_7_diff items.

## Summary

**Line counts:** PRD.md = 382 lines, PRD_FINALIZED.md = 382 lines (0% delta — all edits are inline sentence-level revisions within existing paragraphs; no sections added or removed).

**Changes:**

- §3.6 — revise — appended a pinning clause to the fourth-leg pump gate: the PUMP requirement is a universality check over recorded deliveries, not an existence requirement — it blocks the `FIELD_INSTALLED` → `READY_FOR_FINAL` leg only while some recorded `PUMP` delivery remains unverified, so zero PUMP deliveries advance freely — `implementation/routes_installations.py:104-109` (`any(mv["material_kind"] == "PUMP" and not mv["verified"])` is vacuously false with no deliveries). Traces to the test-suite fix in `test_07_inspections_and_materials.py::test_action_endpoint_conditional_pump_gate`.
- §3.9 — revise — remediation gate now accepts an installation whose permit pins the case's `replacement_design_id` **or a descendant amendment of it**, with the chain direction pinned ("walking its own `supersedes_design_id` amendment chain per §3.3 leads back to the case's replacement design") — `implementation/routes_repairs.py:112-127` + `implementation/services.py:53-72` (`design_descends_from`).
- §3.9 — revise — auto-resolve trigger widened identically ("a permit pinning the replacement design — or a descendant amendment of it") and the final estimate's recording location pinned: recorded on the issuance-pinned design row's `provisional_estimate_cents` — `implementation/services.py:220-229` (`complete_installation`).

**Per-edit pre-edit search log:**

1. **Pump-gate edit (§3.6).** (a) Subject: whether zero PUMP deliveries block the READY_FOR_FINAL leg. (b) Enumerated/read: `routes_installations.py:74-118` (full `advance_installation` — state/site/permit-window/hold-point/material checks), `routes_installations.py:18-35` (`ADVANCE_NEXT`, `LEG_HOLD_POINT`, `LEG_MATERIAL_KINDS` — no PUMP entry; FIELD_INSTALLED leg's only material check is the PUMP conditional), `routes_installations.py:35` (`PUMP_REQUIRED_SYSTEM_TYPES` — GRAVITY/MOUND skip the check entirely), `services.py:75-77,144-153` (delivery/verification helpers — gate-irrelevant), and the edited test at `test_07_inspections_and_materials.py:232-264`. (c) Wording scoped explicitly to "This pump requirement" so it neither redefines nor creates contrast with the parallel TANK/PIPE/AGGREGATE/CHAMBER legs (which share the impl's `any()`-based vacuous semantics but were not a Step 7 item and were left verbatim per hard scope).

2. **Remediation-gate edit (§3.9).** (a) Subject: which existing installation satisfies `ERR_REMEDIATION_NOT_STARTED`'s gate. (b) Enumerated/read: `routes_repairs.py:100-129` (`begin_remediation` — iterates `svc.installations_of_site` with no status filter on installation or permit, self-match included via `design_descends_from`'s first iteration), `services.py:53-72` (chain walk direction: from the permit's pinned design upward via `supersedes_design_id`; cycle-guarded), `routes_repairs.py:53-97` (triage still sets `replacement_design_id` literally to the referenced APPROVED row — untouched by my wording), `routes_flat.py:109-110` (`GET /designs/{did}/repair-cases` filters literal `replacement_design_id` equality — my wording frames the chain rule as local to the gate, not a redefinition of the field). (c) Initial parenthetical ("reachable from it by following `supersedes_design_id` links") was direction-ambiguous — it read as walking from the case's design toward ancestors; revised to "walking its own `supersedes_design_id` amendment chain per §3.3 leads back to the case's replacement design," exactly matching `design_descends_from`'s walk direction.

3. **Auto-resolve edit (§3.9).** (a) Subject: which installation completion auto-resolves a replacement case, and where the final estimate is recorded. (b) Enumerated/read: `services.py:209-229` (`complete_installation` — same `design_descends_from` predicate, restricted to `IN_REMEDIATION`/`REPLACEMENT` cases on the site; writes `provisional_estimate_cents` on the permit-pinned `design` row from that row's current `design_daily_flow_gpd` × 4200 via `replacement_estimate_cents`, HALF_UP), `services.py:156-158` (rate/rounding), `routes_installations.py:223-244` + grep for `complete_installation` (sole caller: FINAL-PASS decide path; FAIL path only forces FAILED_HOLD), `routes_repairs.py:132-143` (manual resolve is REPAIR_IN_KIND-only, so no competing replacement-resolution path), `routes_repairs.py:91-96` + `routes_designs.py:51` (only other writers of the field: triage-time stamp and creation-time null — consistent with "provisional stays on the triage-time row" as the edited test asserts at `test_09_repair_cases.py:84-88`). (c) Kept the existing "which may differ … amended between triage and issuance" clause verbatim and cross-referenced the gate ("in the same amendment-chain sense as the remediation gate above") so both sites share one chain semantics; the recording-location clause is scoped to "at that moment" of an actual auto-resolve, matching the impl's per-matching-case write inside the `IN_REMEDIATION` filter (idempotent across multiple matching cases).

File: `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T14:05:00.000Z

Verbatim subagent summary:

All 16 hunks applied cleanly; line count unchanged (382 → 382), all edits in-paragraph. The deliverable is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1721_septic_system_design_installation/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (382 lines, 62,737 chars) → `PRD_COMPLETED.md` (382 lines, 64,853 chars; **+2,116 chars**, +0 lines). All changes are inline inserts/revisions; no sections added.

**Counts**: 14 ambiguity-pins, 2 mismatch-revisions (16 hunks total).

**Changes** (each: section — insert|revise — kind — what — impl ref):

- §2.1 — revise — ambiguity — unrecognized `X-User-Role` string (outside the six roles) pinned to `ERR_FORBIDDEN` 403, same as a disallowed role — `implementation/middleware.py:23-26`
- §2.3 — revise — ambiguity — `limit`/`offset` parsing pinned: non-integer → `ERR_INVALID_REQUEST`; out-of-range clamped (limit→[1,100], offset→0); echoed `meta.limit` reflects the clamp — `implementation/response.py:33-57`
- §2.3 — revise — ambiguity — `created_at`-ascending ties pinned to insertion order — `implementation/db.py:77-78`
- §2.3 — insert — ambiguity — filter semantics pinned: string equality; `verified` matches `true`/`false` case-insensitively; null fields never match — `implementation/helpers.py:117-134`
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — `implementation/db.py:55`
- §2.6 — revise — ambiguity — `by_periods` must be an integer ≥ 1 else `ERR_INVALID_REQUEST` — `implementation/routes_customers_sites.py:87-89`
- §2.9 — revise — ambiguity — body-FK list extended with `supersedes_design_id` and `site_id` (both enforced as `ERR_FK_NOT_FOUND` 422) — `implementation/routes_designs.py:29`, `implementation/routes_customers_sites.py:138-141`
- §3.2 — revise — ambiguity — `minutes_per_inch` stored exactly as supplied; only the 0.5–240.0 range is enforced (no tenth-rounding) — `implementation/routes_science.py:45-47`
- §3.5 — revise — ambiguity — `permit_number` format pinned: `PER-` + zero-padded six-digit issuance sequence — `implementation/db.py:38-39`
- §3.5 — revise — **mismatch** — suspension sweep set was "anywhere from NOT_STARTED through READY_FOR_FINAL"; impl also sweeps installations already in `FAILED_HOLD` (re-stamped in place with the §2.4 version bump) — `implementation/services.py:183-189`, `implementation/constants.py:47-54`
- §3.6 — insert — ambiguity — explicit definition: non-terminal installation states = `NOT_STARTED`, `ROUGH_IN_PROGRESS`, `TANK_SET`, `FIELD_INSTALLED`, `READY_FOR_FINAL`, `FAILED_HOLD` (governs all cascade sweeps, incl. revoke→`ABANDONED` from `FAILED_HOLD`) — `implementation/constants.py:47-54`
- §3.6 — revise — ambiguity — installation creation performs no permit-status check (FK existence only); the `ISSUED` requirement bites at advance/remediate — `implementation/routes_installations.py:38-53`
- §3.6 — revise — ambiguity — a passed inspection keeps any supplied `decision_note` verbatim with no length requirement — `implementation/routes_installations.py:232-237`
- §3.6 — insert — ambiguity — verifying an already-verified delivery → `ERR_INVALID_STATE` — `implementation/routes_installations.py:293-295`
- §3.8 — revise — **mismatch** — `education_completed_at` was "a logical timestamp derived from the site's `current_period_index`"; impl stamps the server's wall-clock ISO 8601 UTC timestamp. Also pinned: HTTP 201 carrying the updated customer record, and delivery is repeatable (re-stamps) — `implementation/routes_customers_sites.py:148-149`
- §3.8 — revise — ambiguity — lapse grace window pinned to 3 periods (`LAPSED`→`EXPIRED` when clock passes `end_period + 3`) — `implementation/constants.py:28`, `implementation/services.py:253-256`
- §3.8 — revise — ambiguity — missing/non-integer `visit_period` fails with `ERR_VISIT_OUTSIDE_CONTRACT` (window check), not a field-range error — `implementation/routes_contracts.py:107-115`
- §3.9 — revise — ambiguity — `REPLACEMENT` triage omitting `replacement_design_id` → `ERR_FK_NOT_FOUND` (422); only a supplied-but-not-APPROVED design yields `ERR_REPLACEMENT_DESIGN_NOT_APPROVED` — `implementation/routes_repairs.py:75-82`

**Notable alignments verified (no change needed)**: all §2.9 precedence orderings match impl check order in every endpoint; sizing math (Decimal, ceil-once, 120-substitution leg diverging from book-flow tank leg) matches §3.3; the two PRD_FINALIZED amendments (pump-gate universality, amendment-chain remediation/final-estimate semantics) match `services.py` exactly; the permit-`FINALIZED`-only-if-`ISSUED` guard in `complete_installation` is unreachable dead code (every permit exit forces installations out of `READY_FOR_FINAL`), so no pin was required.

## Final Verification Sweep — 2026-08-14T14:10:00.000Z

Orchestrator re-ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`) after Step 9 to regenerate the `results.{1..8}.json` artifacts (absent from disk after the Step 7 subagent exited) and independently confirm the pass. Result: **89/89 passed, 0 failed, in all 8 rounds**. Artifacts persisted at `workspace/implementation/results.{1..8}.json`.

Pipeline complete: Steps 1–9 done. `workspace/PRD_COMPLETED.md` exists.

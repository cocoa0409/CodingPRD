# Worklog — task_0624_allergy_immunotherapy

Scenario: 624. Allergy & Immunotherapy Clinic: testing (skin/blood) & panel, diagnosis & immunotherapy plan, allergy-serum mixing & vial/lot tracking, build-up vs maintenance dosing schedule, in-office shot visits & wait-observation, refill & expiration, billing (antigen units/injection codes), reaction/epinephrine protocol

Difficulty band: Expert

## Step 1: Create task directory — 2026-06-22T11:33:34.639Z

Created `./tasks/task_0624_allergy_immunotherapy/` and `./tasks/task_0624_allergy_immunotherapy/workspace/` via `mkdir -p`.

## Step 2: Generate Scaffold — 2026-06-22T11:33:34.639Z

Generated all three scaffold artifacts for **task_0624_allergy_immunotherapy** at the **Expert** difficulty band, designed purely from the scenario description and the skill spec (no sibling tasks consulted). `scaffold_lint.py` reports **VERDICT: clean lint** (all 385 §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0624_allergy_immunotherapy/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design` key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design` key)

**Complexity profile:** primary archetype workflow_orchestration + secondary compliance_audit; flat topology; branching state-machine shape; peer_roles; immediate consistency. Layers: dual-variant calculation, cascading side effects, scheduled actions (logical clock), derived-field reconciliation.

**Structural counts:**
- **8 entities** — Patient, DiagnosticPanel, AllergenTest, ImmunotherapyPlan, SerumLot, SerumVial, ShotVisit, BillingEntry (8 FKs, all with reverse-reachability GETs). Kept dense rather than padded to the band's 10-15; every other Expert dimension meets/exceeds the band.
- **6 state machines** — including ShotVisit branching fork (RELEASED / REACTION_LOCAL / REACTION_SYSTEMIC with divergent side-effects) and ImmunotherapyPlan ACTIVE↔HELD revert cycle.
- **2 concurrency rules** — OCC on `ImmunotherapyPlan.version` for vial-mix and shot-visit writes (412 ERR_STALE_PLAN_VERSION).
- **6 calculations** — panel_sensitization_score (screening vs clinical dual-variant), dosing_schedule (build-up/maintenance), reaction_reduction, antigen_units (round-at-end), billing_charge (95165 provisional vs final dual-variant), observation_window.
- **17 validations** (priority-ordered), **33 endpoints**, **31 error codes** (every error referenced), **5 roles** (Allergist, Pharmacist, Nurse, Biller, FrontDesk; all opaque identity).

**Difficulty design:** 9 rule_ids × 2 instances = **18 instances**, each with executable setup_api_calls chains, literal-pinned formula asserts (verified in Python), and differentiation clauses satisfied.

**Corner design:** 9 taxonomy sections, **31 active instances + 9 excluded_because stubs** (all stub references resolve to named §1.8 instances).

File sizes: SCAFFOLD.yaml 962 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1116 lines, SCAFFOLD_CORNER_DESIGN.yaml 1247 lines.

## Step 3: Copy shared files — 2026-06-22T12:00:00Z

Copied `./INSTRUCTION.md` → `tasks/task_0624_allergy_immunotherapy/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T12:00:00Z

Generated `workspace/PRD.md` — prose-style PRD for the Allergy & Immunotherapy Clinic API (Expert band). ~6,200 words, 300 lines.

**Sections covered:**
- §1 Introduction (domain + safety + technical framing)
- §2 Global Specs — 9 subsections: RBAC (5 opaque roles), Response Structure (verbatim fixed block), Pagination, Common Resource Properties, Hierarchical Consistency/Cascades, OCC, Logical Clock, Precision/Rounding, Concentration tiers & build-up ladder
- §3 Business Logic — 9 subsections by entity lifecycle: Patients, Diagnostic Panels & Testing, Plan Authoring/Activation, Serum Lots & Recalls, Mixing Vials, Shot Visits & ladder, Completing/Discontinuing, Reaction-Driven Reduction, Billing
- §4 Endpoint table (33 endpoints)
- §5 Error catalogue (32 error codes)

**Hard Contracts — all PASS (verified programmatically):**
- Contract 1 (Field-Name Coverage): entities 52/52, request_body 21/21, query/path params 18/18 — 0 missing (fixed one omission: `to_iso8601` added to §2.7).
- Contract 2 (Rule Coverage): all 32 error IDs, all state enum values, all field-constraint enum values present in prose; both OCC rules expressed; all calculations and cascades translated.
- Contract 3 (§3 Path Purity): 362 §3 backtick tokens scanned — 0 leaked endpoint paths/methods.

§2.2 verified byte-for-byte against canonical fixed block.

**Confirmation:** Subagent did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-22T12:13:00Z

Generated complete test infrastructure following the design-index-only contract.

### Test helpers (Stage 1) — 9 files
Under `test_helpers/`: `__init__.py` (barrel export), `types.py` (8 entity TypedDicts + 12 status/role enums), `api_client.py` (one method per endpoint, 33 endpoints), `api_errors.py` (`ApiErrorId` enum, 30 errors + HTTP status map), `assertions.py` (per-entity structural assertions), `factories.py` (payload factories, PRD-exact names), `constants.py` (clinical thresholds), `test_users.py` (shared role-header constants; all 5 roles opaque), `fixtures.py` (composite setup helpers).

### Test suite (Stage 2) — 6 test files, 67 test functions
`test_01_diagnostics_scoring.py` (10), `test_02_panel_plan_state_machines.py` (9), `test_03_dosing_observation.py` (12), `test_04_cascades_billing.py` (5), `test_05_validations_rbac_concurrency.py` (13), `test_06_difficulty_complementary.py` (18), plus `conftest.py`.

### Coverage (verified programmatically)
- Queue A (Difficulty): all 18 instances across 9 rules translated, exactly 2 tests each (36 tests).
- Queue B (Corner): all 31 non-stub instances translated, 1 test each (31 tests).
- Skipped: 9 `excluded_because:` corner stubs correctly NOT translated (assertions owned by cited difficulty instances); all 9 cross-refs resolve. No instances skipped for PRD-coverage failure.

### Quality gates passed
Every test docstring ends with exactly one `Design:` line resolving to a real instance (no untagged/dual-tagged/broken tags). All quoted PRD citations verified verbatim (fixed 4 ellipsis-fused citations). No scaffold-leakage terms, no skip/xfail, all files compile, 67 tests collect cleanly.

## Step 6: Generate Implementation — 2026-06-22T12:13:00Z

Built complete Python + Flask implementation in `workspace/implementation/`.

### File list
`start.sh` (executable launcher, foreground `exec python3 app.py`, guarded pip install), `requirements.txt` (Flask==3.0.3), `app.py` (33 endpoints, error handlers, route logic in validation-priority order), `db.py` (in-memory store + stamp_create/touch), `clock.py` (logical clock default `2026-01-01T00:00:00Z`), `calc.py` (all calculations), `services.py` (vial volume bookkeeping, 95165 reconciliation, 3 cascades), `serialize.py` (per-entity projections), `response.py` (envelope helpers), `auth.py` (X-User-ID/Role + RBAC), `validate.py` (body/pagination parsing), `errors.py` (full error catalog).

### Storage
In-memory only: Python dicts keyed by UUID (patients, panels, tests, plans, lots, vials, visits, billing_entries) + logical clock. No SQLite, no disk persistence. `store` singleton constructed empty at import; every start.sh reboot wipes state.

### start.sh
Reads `$PORT` (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`. Dependency install guarded so per-test reboots skip pip.

### No seeding
Confirmed: no seed functions, no preloaded entities. All entities built via declared API surface.

Subagent reports all 10 modules compile and server boots/serves via `bash start.sh`; live-verified envelope, clock default, auth, tier derivation, IgE boundaries, dosing ladder, OCC, observation window, cascades, billing.

## Step 7: Run Tests and Iterate — 2026-06-22T12:30:00Z

Final 8-round parallel sweep: all 8 rounds pass 67/67. (Confirmed via results.{1..8}.json.)

**Iterations run:** 2 (1 diagnostic sweep + 1 verification sweep). All 8 parallel rounds now pass 67/67.

**Tests deleted:** None. Every failing test asserted a PRD-covered, uniquely-derivable rule; the failures were all test/fixture bugs, not unfair assertions.

**Root causes diagnosed:**
1. **Release endpoint returns the visit, not the plan.** `POST /shot-visits/{visitId}/release` returns the updated visit object (PRD §2.2 + §3.6 frame the visit as the operation's resource, consistent with every other endpoint returning its own path resource). The fixtures/tests wrongly read plan fields (`version`, `current_step_index`, `current_vial_color`, `status`) off the release response — the visit's `version` differs from the plan's after the ladder advance, causing `ERR_STALE_PLAN_VERSION` (412) downstream and a `KeyError: 'current_step_index'`.
2. **Observation-window boundary tests hardcoded 30 min.** PRD §3.6 uniquely dictates the extended **45 min** window for the first dose on a fresh plan (escalation: scheduled 0.10 > `last_dose_volume_ml` default 0). The boundary tests assumed 30 and released too early, hitting `ERR_OBSERVATION_NOT_ELAPSED`.

**Fixes applied to `test_helpers/` (1 file):**
- `fixtures.py` — `administer_and_release`: stopped treating the release response as the plan; now re-fetches the plan via `get_plan(plan_id)` after release.

**Fixes applied to `test_suite/` (4 files):**
- `test_02_panel_plan_state_machines.py` — `test_plan_held_then_resume_reverts_to_active`: re-fetch plan via `get_plan` after release instead of reading plan fields off the visit response.
- `test_04_cascades_billing.py` — `test_95165_provisional_reconciles_to_final_on_discontinue`: same re-fetch fix so the second shot carries the plan's current version.
- `test_06_difficulty_complementary.py` — `test_released_branch_advances_ladder`, `test_resume_applies_reduced_re_entry_dose`, `test_antigen_units_red_step_two_round_at_end`: assert the release returns the RELEASED visit, then re-fetch the plan for ladder/version assertions; `test_release_after_observation_boundary_accepted`: corrected to the PRD-derived 45-min window (release at 09:46).
- `test_03_dosing_observation.py` — `test_release_at_exact_observation_boundary_accepted`: corrected window assertion to 45 and inclusive-boundary release to exactly admin+45 (09:45), with docstring updated.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout (release returns its path resource; window correctly computes 45 on escalation; reentry-override dose-reduction correct). No implementation check was weakened or removed.

## Step 8: Finalize PRD — 2026-06-22T12:31:00Z

Ran (skip condition not met: Step 7 had 1 test_helpers/ fix + 5 test_suite/ fixes, though 0 deletions and 0 implementation/ fixes). Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 300 lines; PRD_FINALIZED.md = 300 lines. Single edit extends an existing §2.2 bullet (no new lines). ~0.0% line-count change.

**Changes (1 edit):**
- §2.2 (API Response Structure) — revise — clarified that an operation which cascades across several resources returns the resource named by the endpoint's own path, not a dependent resource; added recall→lot, discontinue→plan, release/record-reaction→visit examples — implementation/app.py:864 (release returns serialize.visit), also :897/:934 (record-reaction), :587 (recall→lot), :522 (discontinue→plan).

**Step 7 item dispositions:**
- Item 1 (release returns the visit, not the plan): PRD edit warranted. §2.2's generic "return the created or updated resource object" was unambiguous only for single-resource operations; release mutates visit+plan+vial and the §3.6 narrative is plan-centric, so a fresh implementer could plausibly return the plan (the divergence Step 7's fixtures assumed). Pinned the path-resource convention in §2.2.
- Item 2 (45-min escalation window): No PRD edit. PRD §3.6 already verbatim and uniquely states 45 min "when the scheduled step volume is higher than the plan's last_dose_volume_ml"; §3.3 fixes last_dose_volume_ml default = 0, so first-dose→45-min is fully derivable. Pure fixture/test bug (boundary tests hardcoded 30).

**Pre-edit search log:** Subject = which resource an action/cascade endpoint returns in `data`. Enumerated every `object_response(serialize.*)` return in app.py (all creates, all action endpoints: finalize→panel, activate/resume/complete/discontinue→plan, recall→lot, administer→visit, release→visit, record-reaction→visit, clock-set→non-entity custom object documented in §2.7). Scoped new sentence to "the resource the path identifier resolves to" under the existing "Unless otherwise noted," prefix so clock-set is exempt; chose broad path-resource framing so all parallel cascade endpoints are covered without a release-only narrowing.

## Step 9: Complete PRD — 2026-06-22T12:39:00Z

Full PRD-vs-implementation scan. Source = `PRD_FINALIZED.md`. Produced `workspace/PRD_COMPLETED.md`.

**File counts:** PRD_FINALIZED.md (source) = 300 lines / 42,741 chars → PRD_COMPLETED.md = 302 lines / 46,201 chars. Char delta +3,460; line delta +2.

**Change counts:** 7 ambiguity-pins, 3 mismatch-revisions (10 edits across 9 passages).

**Per-change bullets:**
- 2.3 Pagination — insert — ambiguity — pinned `created_at` tie-break by ascending lexicographic `id` — app.py:117.
- 2.4 Common Resource Properties — insert — ambiguity — pinned `version` begins at 1 — db.py:48.
- 2.6 OCC — insert — ambiguity — omitting/non-integer `expected_plan_version` → ERR_INVALID_REQUEST (boolean = non-integer) — app.py:123-131.
- 2.6 OCC — insert — ambiguity — OCC guard precedence: after path + body-FK resolution, before entity-state errors — app.py:602-611, 692-703.
- 2.6 OCC — revise — mismatch — resume now requires `expected_plan_version` (omission → ERR_INVALID_REQUEST) — app.py:468.
- 3.1 Patients — revise — mismatch — `date_of_birth` accepted as any non-empty string, not updatable on PATCH; update applies full_name/epinephrine_on_file/status only — app.py:197-212, validate.py:62-66.
- 3.2 Diagnostic Panels — insert — ambiguity — empty-panel screening_composite = 0; creation defaults (composites 0, tier LOW) — calc.py:113-114, app.py:234-236.
- 3.6 Shot Visits (administration) — insert — ambiguity — injection_count integer ≥1 else ERR_INVALID_REQUEST; visit persists/returns released_at_iso, reaction_grade (null→NONE), epinephrine_administered (default false) — app.py:689,761-764, serialize.py:89-103.
- 3.6 Shot Visits (preconditions) — revise — mismatch — SILVER epinephrine gate checked before volume check; full ordering plan-state → vial-plan → usability → epinephrine → volume — app.py:699-740.
- 3.6 Shot Visits (dose) — insert — ambiguity — scheduled_dose_volume_ml is always ladder/maintenance lookup; re-entry override replaces (not subtracts) for administered_volume_ml; both stored rounded 2dp — app.py:725-732,755-756, calc.py:181-184.
- 3.6 Shot Visits (record-reaction) — insert — ambiguity — reaction_grade mandatory; visit-state check precedes grade check; grade NONE → ERR_REACTION_GRADE_MISMATCH — app.py:872-880.
- 3.9 Billing — insert — ambiguity — summary shape: returns patient_id; reversed_total_cents sums REVERSED charge_cents; by_cpt object keyed by cpt_code summing non-REVERSED, omitting empty codes — app.py:973-992.

No new sections; all edits in-paragraph. Behaviors already uniquely pinned (scoring formulas, ladder steps, shelf life, dilution factors, cascade hops, RBAC, error catalogue, clock default/expiry, antigen-unit rounding, needs_refill threshold) left unchanged.

---

## PIPELINE COMPLETE

All 9 steps finished. Final 8-round stability sweep: 67/67 tests pass in all 8 parallel rounds. Task directory contains SCAFFOLD (×3), PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (67 tests), workspace/implementation/ (working Python+Flask server, in-memory only).

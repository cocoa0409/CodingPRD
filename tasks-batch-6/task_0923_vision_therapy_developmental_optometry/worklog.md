# Worklog — task_0923_vision_therapy_developmental_optometry

Scenario (verbatim): `923. Vision Therapy & Developmental Optometry: evaluation & binocular assessment, therapy plan & in-office/home sessions, progress & reassessment, medical vs vision billing, activity/equipment kit, scheduling & therapist, discharge, referral`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-04T03:59:48.888Z

Created `tasks/task_0923_vision_therapy_developmental_optometry/` and `workspace/`. Index 0923 = max existing (0922) + 1. Note: a co-tenant pipeline holds `task_0922_hormone_pellet_wellness_injection` (created same minute, 5 other `claude -p` sessions live) — sweep sizing must assume a shared host.

## Step 2: Generate scaffold — 2026-08-04T04:56:08.942Z

All three scaffold artifacts are written and verified.

## Files

- `SCAFFOLD.yaml` (3,650 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,654 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (6,065 lines)

## Counts (gate values)

| Dimension | Target | Delivered |
|---|---|---|
| Entities | 15–16 | **16** |
| Endpoints | 62–70 | **69** (all under `/vision-therapy`, path params uniformly `{id}`) |
| State-machine axes | 11–13 (≥8 non-linear) | **12 axes over 11 entities; 11 non-linear** (only `Patient.clinical_status` is linear) |
| Calculations | 14–18 (≥5 dual-variant) | **18, 5 dual-variant** |
| Error codes | 30–36 | **36** |
| Ladder rungs | 25+ | **36** |
| OCC rules | 3 | **3** (Authorization / TherapyPlan / Coverage) |
| Conservation invariants | 3–4 | **4** (visit units, kit units, claim dollars, vision allowance dollars) |
| Cascade depth | ≥5 | **5** (CASCADE-A) + a 4-link CASCADE-B from a different trigger |
| Declared constants | all valued | **85, zero undeclared** |
| Design instances | ≥18 §1.8 | **19 §1.8** (2–3 per rule, all 9 rules) + **63 §1.9** (9 sections, 3 stubs); 82 unique names |

Non-linear axes: Assessment (capped DRAFT→FINALIZED→SIGNED→DRAFT), TherapyPlan.status (suspend/resume + revision cycles), TherapyPlan.progress_state (independent second axis with a plateau fork), PlanPhase (MASTERED→IN_PROGRESS regression), TherapySession.schedule_status (two entry points), TherapySession.billing_status (independent second axis), Authorization (ACTIVE↔EXHAUSTED), Claim (capped appeal cycle), Referral (capped retry → ABANDONED), KitLoan (fork on `item_class`), OcclusionPrescription (taper self-loop).

Dual-variants sit on five different entity domains: amplitude reference band (STANDARD 15−0.25·age vs FUNCTIONAL 16−0.28·age), session units (stepped minutes vs flat), claim money (medical deductible-then-coinsurance vs vision allowance), composite progress score (binocular-weighted vs acuity-weighted), discharge readiness (METRIC vs GOAL).

## Reachability repairs made

1. **Rung 23 was unreachable** — an exhausted pool auto-transitions to `EXHAUSTED`, and a naive rung-14 "authorization must be ACTIVE" would always pre-empt `ERR_AUTH_VISITS_EXHAUSTED`. Repaired by declaring `EXHAUSTED` an *open* state at rung 14 (`status IN {ACTIVE, EXHAUSTED}`), so rung 23 fires. Rung 14 still rejects `CLOSED`/`EXPIRED`, which a corner instance asserts as the contrast.
2. **`OCCLUSION_MAX_DAILY_HOURS = 7` was an unhittable boundary** — every ladder cell was ≤ 7. Repaired by setting the OLDER×SEVERE cell to a raw 8 hours so the cap actually clips.
3. **Global write gate would have starved rungs 13–36** — repaired with an explicit exclusion list (all five claim endpoints, kit return, referral respond, authorization close, coverage create, discharge itself, all GETs, all config POSTs, the clock). Stated in `complexity_profile.design_notes`, in rung 12, and asserted by two corner instances.
4. **Discharge cannot leave an outstanding loan** (rung 27), so "kit return after discharge" looked unreachable — repaired by routing the corner test through a still-`REQUESTED` loan (rung 27 only blocks `CHECKED_OUT`/`RECALLED`), which returns to `CANCELLED`.
5. **`suspension_reason: AUTHORIZATION_LAPSE` had no producer** (enum-closure dead end) — removed from the enum.
6. **Compliance denominator was circular** (advancing a phase changes the denominator of the metric gating the advance) — pinned to the prescription in force at window start via `previous_prescribed_home_sessions_per_week` / `prescription_changed_at`.
7. Removed one §1.9 stub whose `difficulty_instance` pointed at a §1.9 (not §1.8) instance; the corner it named is covered by a real recipe instead.

## Verification

- All three files `yaml.safe_load` cleanly (two lint classes fixed en route: PyYAML rejects a bare `?` inside a flow sequence — every `field?` in an `input:` flow list is quoted; and `$.data[0].x` must be quoted inside a flow mapping).
- `scaffold_lint.py <task-dir>` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     16
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1679

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

- Zero unbound `${var}` across 1,679 calls; every OCC `expected_*_version` is a captured `${var}`; every error code is referenced by a rung; no forbidden concurrency vocabulary; no tabs; scenario string verbatim.
- Every formula-derived assertion literal was computed in Python first (59.31 / 59.09 / 60.02 composite scores, 41.60 + 60.40 + 24.00 = 126.00 medical split, 126.00 vision, 116.88 vs 116.87 damage-fee rounding-order divergence, 36.00 salvage floor, 75.00 compliance, 42.00/84.00 unit-step boundary, 210.00 evaluation).

**Orchestrator independent verification:** all three files re-parsed with `yaml.safe_load` (OK); `SCAFFOLD.yaml` has 69 `endpoints[]` / 16 `entities[]`; independent ALL_CAPS sweep found 85 constants declared with values and 51 constant-shaped tokens, of which the only 6 not carrying a value are error codes (`ERR_APPEAL_LIMIT_REACHED`, `ERR_COMPLIANCE_BELOW_THRESHOLD`, `ERR_REFERRAL_ATTEMPT_LIMIT`, `ERR_SESSION_OUTSIDE_AUTH_WINDOW`, `ERR_THERAPIST_DAILY_CAP_EXCEEDED`, `ERR_VISION_FREQUENCY_LIMIT`) — **0 undeclared constants**.

## Step 3: Copy shared files — 2026-08-04T04:56:08.942Z

`cp ./INSTRUCTION.md tasks/task_0923_vision_therapy_developmental_optometry/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-04T05:16:00.000Z

PRD written to `workspace/PRD.md`.

## Size
**554 lines, 16,899 words.** Structure: §1 intro (3 paragraphs), §2 with 12 domain-derived subsections, §3 with 11 workflow subsections, §4 endpoint table (4 columns), §5 error table (2 columns). Document ends at the §5 table — no audit footer. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

## Coverage audit (all counts verified by grepping the generated file, not estimated)

| Item | Required | Verified present | Method |
|---|---|---|---|
| Endpoints | 69 | 69 | every scaffold `path` matched as a `\| \`path\` \|` row in §4; 69 table rows counted |
| Entity field names | 175 | 175, 0 missing | backtick-token diff (fenced blocks stripped) |
| Endpoint input/query/path identifiers | 114 | 114, 0 missing | same diff |
| State-machine axes | 12 | 12 | all 45 distinct state values present; all **54** unique `(entity, axis, from, to)` transitions expressed — 32 via `X → Y` arrow pairs, the other 22 verified individually in prose |
| Calculations | 18 | 18 | walked one-by-one; all 5 dual-variant calcs render both forks *and* the fork condition |
| Error codes | 36 | 36 in §2/§3 narrative **and** 36 in the §5 table | programmatic diff both ways |
| Validation rungs | 36 | 36 numbered, in scaffold priority order, each with check + error id + HTTP status + `applies_to` scope | `^[0-9]+\. \*\*` count = 36 |
| OCC rules | 3 | 3 | each names write endpoint + `expected_*_version` + `ERR_STALE_VERSION` + 412, in §2.9 and again at point of use |
| Conservation invariants | 4 | 4 | each with its full `holds_after` list |
| Constants | 85 | 85 values rendered inline at point of use | value-variant search over §1–§3 only (excludes §4/§5 tables); zero missing |

Write gate: §2.8 lists **29** gated endpoints and **16** excluded write endpoints; verified programmatically that the two lists partition all 45 POST endpoints exactly and that the gated set is set-identical to rung 12's declared family.

**Contract 1** PASS (175/175 entity fields, 114/114 input identifiers, 0 missing). **Contract 2** PASS. **Contract 3** PASS — 1,257 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos, 0 raw `/vision-therapy` mentions. §2.2 verified byte-identical to `section-2.2-response-structure.md`.

## Under-determined friction points (note 6) — written visibly and un-prejudged, listed here for carry-forward

1. **Role↔credential correspondence.** Rung 2's declared check is existence of the backing row (plus `PatientUser` ownership). The role definitions say each clinical role's `X-User-ID` names a `Therapist` with a specific `credential`, but no rejection is declared for a mismatch. §2.1 states both facts side by side and explicitly notes no separate rejection is specified.
2. **`therapy_indicated`'s amplitude term.** The `Assessment.therapy_indicated` field description says "amplitude falls below the **STANDARD** expected minimum", while `npc_threshold_evaluation` says "the amplitude row's own `diagnostic_flag` is true" — and that flag is measured against whichever variant the row carries. These diverge on a `DISCHARGE_READINESS` battery. The PRD follows the calculation (the row's own variant) and makes the variant-carrying explicit.
3. **CASCADE-A hop 2 scope.** The scaffold does not say whether only cascade-created urgent outbound referrals suspend a plan, or any manually created one. The PRD states the general rule (any `OUTBOUND`+`URGENT` referral naming an `ACTIVE` plan), which both the axis-3 trigger text and `Referral.plan_id`'s description support.
4. **CASCADE-B hop 5 authorization scope.** The scaffold does not say which authorizations close. The PRD states the reachability path — each discharged plan's `authorization_id` — and adds explicitly that a `DRAFT` plan has a null `authorization_id` and closes nothing, and that an authorization no discharged plan references is not reached by this path.
5. **`discharge_ready` recomputation timing.** It is recomputed only at assessment *finalize*, yet both variants read only `SIGNED` assessments — so the battery that would make a plan ready cannot do so at its own finalize, and nothing recomputes at sign time. This has a live consequence for `GOALS_MET` discharge (rung 35). §3.7 states it explicitly rather than papering over it.
6. **`patient_age_years` on occlusion prescriptions.** The calculation's trigger lists occlusion creation, but `OcclusionPrescription` carries no such field; `occlusion_daily_dose` reads `source_assessment.patient_age_years`. The PRD uses the source assessment's stored value.
7. **`plan_id` required on a `REASSESSMENT`.** Stated only in the field description; no rung names it. The PRD treats it as a rung-3 required-field failure (`ERR_VALIDATION`).
8. **`quantity == 1` for `LOANABLE_SERIALIZED`.** The field description reads as a creation-time constraint, but rung 28 checks it only at fulfilment and routes it to `ERR_KIT_STOCK_DEPLETED`. The PRD states enforcement at fulfilment, per the rung.

## Step 5: Generate unit tests — 2026-08-04T05:51:41.000Z

All three stub cross-references resolve. The suite is complete and verified.

### Files written

**`test_helpers/`** (2,601 lines) — `types.py` (39 enums + 17 entity TypedDicts; `BinocularMeasurement` correctly omits `updated_at`/`version`), `api_client.py` (all 69 endpoint methods), `api_errors.py` (36 error ids + status map, registered with the framework), `assertions.py` (per-entity assertions, all four conservation-identity checkers, `parse_instant`/`assert_same_instant`/`assert_three_fractional_digits`), `factories.py`, `constants.py`, `test_users.py` (per-instance builders for all four entity-backed roles plus distinct-operator builders for `BillingSpecialist`), `fixtures.py` (747 lines, 5 tiers — `setup_clinic_configuration`, `setup_active_plan`, `deliver_session`, `checked_out_loan`, `setup_occlusion_scenario`, …), `__init__.py`.

**`test_suite/`** — `conftest.py` plus 12 test files:

| File | Tests |
|---|---|
| `test_01_patient_registration_and_record_identity.py` | 6 |
| `test_02_binocular_battery_lifecycle.py` | 8 |
| `test_03_coverage_authorization_and_progress_scoring.py` | 11 |
| `test_04_therapy_plan_and_phase_ladder.py` | 5 |
| `test_05_session_scheduling_contention.py` | 13 |
| `test_06_session_delivery_and_billing.py` | 8 |
| `test_07_home_practice_and_compliance.py` | 6 |
| `test_08_occlusion_prescriptions.py` | 4 |
| `test_09_equipment_kit.py` | 7 |
| `test_10_claims_adjudication.py` | 10 |
| `test_11_cascades_referrals_and_discharge.py` | 11 |
| `test_12_access_control_and_concurrency.py` | 9 |
| **Total** | **98** |

### Coverage

- **Queue A (Difficulty)**: 19/19 instances rendered, each with exactly 2 tests (38 tests).
- **Queue B (Corner)**: 60/60 non-stub instances rendered, 1 test each (60 tests). The 3 `excluded_because:` stubs were not translated; all three `difficulty_instance` cross-references verified to resolve (`room_conflict_versus_credential_expiry_precedence` → `credential_expired_pre_empts_room_conflict`, `visits_exhausted_error_trigger` → `room_conflict_pre_empts_visits_exhausted`, `kit_stock_depleted_error_trigger` → `kit_stock_conserved_across_checkout_then_lost_return`).
- **Instances SKIPPED for PRD-filter failure: none.** Every non-stub instance passed both conditions. Where an instance brushed one of the 8 friction points, the PRD still uniquely determined the asserted outcome, so nothing had to be dropped:
  - *(2) amplitude term in `therapy_indicated`* — the one test asserting `therapy_indicated` (`evaluation_signature_promotes_patient_from_intake_to_active`) reaches `true` through the NPC diagnostic breach, so the amplitude variant is not load-bearing.
  - *(3) CASCADE-A hop 2 on manual referrals* — every manually created referral in the indices is `ROUTINE`, so hop 2 never applies; no test depends on the ambiguity.
  - *(5) `discharge_ready` recomputation* — both tests asserting it (`composite_score_uses_the_acuity_variant_for_amblyopia`, `outstanding_loan_rung_pre_empts_the_discharge_criteria_rung`) assert `false` in a state where no SIGNED battery of either kind exists, which both readings agree on.
  - *(1), (4), (6), (7), (8)* — no instance's assertion depends on them.
- **Assertions dropped from otherwise-rendered instances** (three, all un-derivable sub-clauses, none affecting the instance's own claim): the "no PUT/PATCH/DELETE endpoint exists" clause (not observable), the "PAYER_TERMINATED / CLINIC_REQUEST are accepted alternatives" clause on `authorization_close_…` (asserts nothing about the trigger), and "updated_at strictly increases across the three reads" on `version_increments_by_one_on_every_mutation` — the logical clock is frozen across those three calls, so strict increase is *contradicted* by PRD §2.5 rather than implied by it.

### Verification performed

- 98/98 tests collected by pytest; all 12 modules import cleanly.
- **238 quoted PRD citations, all verbatim** against a whitespace-normalized grep of `PRD.md` (0 failures).
- Every test carries **exactly one** `Design:` tag, and every tag resolves to a real instance in the source yaml.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no scaffold references leaked into comments or docstrings.
- All instant comparisons routed through `assert_same_instant` (never raw string equality); distinct `X-User-ID` values used for every owner the PRD requires to differ (biller-1/biller-9/biller-2 on claim correction, od1/od2 on reassessment signature, two distinct patient ids on cross-patient attestation).
- `workspace/implementation/` was never read, listed, or grepped.

## Step 6: Generate implementation — 2026-08-04T05:51:41.000Z

Cleanup done (the one remaining `app.py` belongs to a co-tenant pipeline, `task_0926`, and was left alone). Implementation complete.

### What was built

`workspace/implementation/` — Python + Flask, 21 modules, **3,997 Python lines** (+ `start.sh` 12, `requirements.txt` 1 = 4,010 total):

| Module | Lines | Module | Lines |
|---|---|---|---|
| `calc.py` | 430 | `store.py` | 206 |
| `routes/sessions.py` | 347 | `config.py` | 201 |
| `routes/plans.py` | 315 | `routes/coverages.py` | 197 |
| `routes/claims.py` | 312 | `routes/kits.py` | 187 |
| `cascades.py` | 273 | `serialize.py` | 165 |
| `routes/assessments.py` | 237 | `routes/referrals.py` | 142 |
| `validate.py` | 226 | `routes/occlusion.py` | 133 |
| `routes/admin.py` | 213 | `lookup.py` | 107 |
| `envelope.py` | 93 | `errors.py` | 88 |
| `auth.py` | 58 | `app.py` | 52 |
| `routes/__init__.py` | 15 | | |

### Completeness gate (note 2)

```
scaffold endpoints declared : 69
distinct declared pairs     : 69
registered pairs            : 69
MISSING                     : 0
EXTRA                       : 0
```
Produced by booting the app in-process, dumping `app.url_map`, and diffing normalized `{id}`↔`<id>` (method, path) pairs against `SCAFFOLD.yaml:endpoints[]`.

### Note 5 adjudications

**Timestamp rule.** Every instant the *server* writes — anything read from the logical clock or arithmetic on it (`created_at`, `updated_at`, `signed_at`, `checked_out_at`, `attested_at`, `recalled_at`, `recall_due_at`, `discharged_at`, `sla_due_at`, `last_reauthorized_at`, `last_appeal_attempt_at`, `prescription_changed_at`, `started_at`, `mastered_at`, `returned_at`, `responded_at`) — renders as `YYYY-MM-DDTHH:MM:SS.sssZ`, exactly three fractional digits (PRD §2.4). Every instant the *caller* supplies (`scheduled_start_at`, `scheduled_end_at`, `performed_at`, `credential_expires_at`, `due_at`) is stored and echoed **byte-for-byte**, never reformatted. `_clock/set_current_utc` echoes `current_utc` verbatim from `to_iso8601`, and exactly `2026-05-01T00:00:00Z` before any set (§2.5 states that literal reading). Verified: a patient created at clock `2026-06-01T00:00:00Z` returns `created_at: "2026-06-01T00:00:00.000Z"` while `credential_expires_at: "2027-01-01T00:00:00Z"` echoes unchanged.

**Enum routing rule.** Rung 4's list is treated as exhaustive and literal: only `diagnosis_category, discharge_reason, payer_type, assessment_type, purpose, metric_code, eye, discharge_criteria_mode, procedure_code, cancel_reason, item_class, returned_condition, service_class, direction, urgency, response_outcome, severity, close_reason, suspension_reason, equipment_class, credential`, the adjudication `outcome`, and every enum-valued *list filter* (`status`, `schedule_status`, `billing_status`, `progress_state`, `modality`, `assessment_type`, `purpose`, `metric_code`, `direction`, `urgency`, `severity`) route to `ERR_INVALID_ENUM`. Everything else — including a **missing or badly typed** value in one of those same fields, and out-of-range pagination — routes to `ERR_VALIDATION`. Mechanically enforced by splitting each enum field into a rung-3 presence/type check and a separate rung-4 membership check, so rung 3 always fires first. Enum *members* are the field's full declared set (e.g. `cancel_reason` accepts all four values, `close_reason` all three) since no rung declares a narrower per-endpoint rejection.

### The 8 friction points

1. **role↔credential** — no rejection. Rung 2 checks only that `X-User-ID` names an existing backing row (§2.1 final paragraph says no separate rejection is specified).
2. **`therapy_indicated` amplitude term** — uses the **row's own variant** minimum, per §3.1/§3.2 prose ("evaluated against whichever variant's minimum the row carries"), not the field-summary's "STANDARD".
3. **CASCADE-A hop 2** — fires for **manually created** urgent outbound referrals too. §3.11 phrases hop 2 as a property of *creating* an OUTBOUND+URGENT referral naming an ACTIVE plan; implemented once in `create_referral_row`, shared by both paths. Verified live.
4. **CASCADE-B hop 5** — closes **only** the authorizations reached through `authorization_id` of the plans hop 1 discharged (de-duplicated, and only those in `ACTIVE`/`EXHAUSTED`/`EXPIRED`). A never-activated DRAFT plan closes nothing.
5. **`discharge_ready`** — recomputed at **every** assessment finalize, on the plan named by `assessment.plan_id` (skipped when null); both variants read only `SIGNED` assessments, so the battery being finalized never counts toward its own recomputation. Verified: METRIC stays false until the `DISCHARGE_READINESS` battery is signed *and* a later finalize triggers the recompute.
6. **`patient_age_years` on `OcclusionPrescription`** — not added as a field. The age band reads the **source assessment's** stored `patient_age_years`; the prescription serializes only its scaffold-declared fields.
7. **`plan_id` on a REASSESSMENT** — **enforced** as a rung-3 `ERR_VALIDATION` ("a REASSESSMENT requires a plan_id" is stated twice, in §3.1 and the field description). An `EVALUATION` forces `plan_id` to null.
8. **`quantity == 1` for `LOANABLE_SERIALIZED`** — enforced **only at fulfilment** by rung 28 (`ERR_KIT_STOCK_DEPLETED`), as rung 28 explicitly states; creation accepts any non-negative quantity. Verified: qty-2 serialized loan creates 201, fulfils 409.

### Other decisions worth flagging

- **Version granularity:** one bump per row per request (a row written several times in one call advances by exactly 1), applied uniformly via a request-scoped touched-set. Secondary rows mutated by a call (plan on session-complete, coverage on claim-create, phases in a cascade) each bump once, per §2.4's universal rule.
- **Rung 3 vs. existence:** ladder order is kept (shape/enum before 404s), except where a rung-3 check is undefined without the row — the finalize "needs one NPC measurement" check runs after assessment resolution but still pre-empts rungs 12 and 14.
- **PatientUser ownership (rung 2):** the target row is peeked silently, ownership 403 fires before shape validation, and the 404 still comes from the proper existence rung.
- **`mastery` on a non-`IN_PROGRESS` phase** and **duplicate `sequence_index`** are not rejected — no rung declares an error for either.
- **`ciss_score` 0–60** and **`coinsurance_rate` 0.00–1.00** are enforced as `ERR_VALIDATION` (both domains are stated in PRD prose).

### Verification

Five live smoke suites (~200 assertions) ran green against a running server, covering: the reference composite scores **59.31 / 60.02 / 59.09**, medical waterfall **41.60 / 60.40 / 24.00**, vision arm + allowance identity, all four conservation invariants, both amplitude bands (12.50/14.50 standard, 13.20 functional), the 22→1 / 23→2 minute step edge, room 14-vs-15-minute buffer, therapist adjacency vs. overlap, 180-minute cap boundary, exact-75.00 compliance pass, compliance denominator pinning to the *previous* prescription, plateau→PLATEAU→REVISION_PENDING, phase regression, both mutate-then-reject rungs (and rung 14 pre-empting rung 36, rung 12 pre-empting rung 33), clock sweeps at the inclusive window edge, and full CASCADE-A/CASCADE-B.

`bash start.sh` from a cold process answered a `POST /vision-therapy/patients` with **HTTP 201 in 0.28 s**, default clock reading `2026-05-01T00:00:00Z`, store empty (no seeding anywhere), `find_spec`-guarded pip, `0.0.0.0:$PORT`, foreground `exec`.

### Orchestrator containment + isolation checks (post Steps 5/6)

- **Isolation overlap direction: Step 5 finished first** (~1,845 s vs Step 6 ~2,000 s), so `test_suite/` was on disk during impl-gen's final ~155 s. Step 6 was instructed not to read it. Containment grep of the whole impl tree for `test_suite|test_helpers|conftest|pytest` returns **empty**. Step 7 is briefed on the overlap.
- Impl persistence grep (`sqlite|json.dump|pickle|/tmp|shelve|.db`) — **empty**.
- Cross-task reference grep (`task_09xx|task_08xx`) across impl + tests — **empty**.
- `def test_` count = **98**; `Design:` tags = **98**; `skip/xfail/skipif` = **0**.
- Independent orchestrator `app.url_map` diff vs `SCAFFOLD.yaml:endpoints[]`: **declared 69 / registered 69 / MISSING none / EXTRA none**.
- Host carries **four co-tenant pipelines** (task_0922, 0924, 0925, 0926) → `workspace/sweep.sh` pre-staged as **4 waves of 2**, `bash -n` clean.

## Step 7: Run tests and iterate — 2026-08-04T06:12:49.582Z

The loop is complete. All 8 rounds pass, twice over.

**Iterations run:** 3 sweeps (24 rounds total). Iteration 1 exposed the defect; iterations 2 and 3 confirmed the fix.

**Tests deleted:** None. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability) — the only failures were infrastructural.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `test_suite/`:** None needed.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — added `_bind_with_retry()` and switched the entry point from `app.run()` to a self-bound socket handed to `werkzeug.serving.make_server(..., fd=...)`.

**The bug, and why the 8-round sweep was the only thing that could catch it.** Iteration 1 came back 96/98 on rounds 1–2 and 98/98 on rounds 3–8 — two tests erroring with *"API server could not be restarted"* after burning exactly 15.07s. Reading the runner source (`prd_bench_local_runner/pytest_plugin.py`) showed the mechanism: `_kill_port()` issues `kill -9` and returns **without waiting** for the socket to be released, then immediately spawns the new server. If the dying process still held the LISTEN socket, the new server hit `EADDRINUSE` — and Werkzeug treats that as fatal, printing to stderr and calling `sys.exit(1)`. The server died instantly and the harness then polled a dead port for its full 15s budget, blaming whichever test happened to be next in line. That's why the same two tests failed in both wave-1 rounds on *different* ports: nothing about those tests was special, they were just standing where the collision landed.

My first attempt (`except OSError` around `app.run`) did **not** work, and I caught it by testing against a genuinely occupied port rather than assuming — Werkzeug converts the error to `SystemExit`, so the handler never fired. Pre-binding the socket ourselves bypasses Werkzeug's fatal bind entirely. Verified directly: the server now waits out a 3-second port occupation and serves correctly at 3.23s, where it previously died at once. Clean boot is unaffected at 0.44s.

The fix is startup-only — no endpoint, response field, side effect, or business behavior changed.

**Passing-test isolation audit** (Steps 5/6 overlapped by ~155s, so I swept all 98 passing tests, not just failures):

| Category | Finding |
|---|---|
| Raw timestamp-string equality | **Clean.** Every instant goes through `assert_same_instant`/`parse_instant`. The single `==` on a date string (`last_paid_service_date_therapy == "2026-06-03"`) is a verbatim copy of a client-supplied `service_date`, per PRD §3.10. |
| List ordering / tie-breaks | **Clean.** Only two positional reads; both are single-row filtered lists with `len(...) == 1` asserted first. Phase ordering traces to PRD §2.3's named exception. |
| Exact `version` values | **Clean.** Five assertions, all `1` at creation or the 1→2→3 walk across finalize/sign, each an explicit PRD "bumps `version`". |
| Response-field projections | **Clean.** `allowed_amount`, `deductible_applied_amount`, `coinsurance_amount`, `appeal_attempt_log_count`, `sla_due_at`, `recall_due_at`, `adjudication_variant` are all PRD-declared attributes, not formula intermediates. |
| Cascade legs that do not fire | **Clean.** All negative assertions map to PRD-declared creation defaults or the four conservation identities. |
| Impl-tree breach probe | **Clean.** No reference to `test_suite`/`test_helpers`/`conftest`/`pytest`/factories/fixtures anywhere in the implementation. |
| Storage discipline | **Clean.** Plain in-memory dicts; no SQLite, file dump, `/tmp` cache, or seeding. |

I also checked all 8 known under-determined friction points: **none is exercised by any test.** FP1 (role↔credential) has no mismatch test; FP3 uses an INBOUND/ROUTINE referral so hop 2 never applies; FP5's `discharge_ready` case resolves False under both readings; FP7 is untested; FP8's test drives the `on_hand` shortfall arm on a `CONSUMABLE_STOCK` item, never the serialized `quantity == 1` arm. Two spot-checked calculations reproduce PRD's own worked examples exactly (damage fee 275 × 17/24 × 0.60 = 116.875 → **116.88**, with a `!= 116.87` guard against wrong-direction rounding; medical waterfall 41.60/60.40; amblyopia composite 59.09).

One judgment call worth flagging: `weighted_minutes` (asserted in `test_07`) is introduced possessively — *"A session's `weighted_minutes` is…"* — and consumed as *"the session's `weighted_minutes`"* in §3.5, but it never appears in a creation-defaults list the way `billable_units` and `charge_amount` do. I judged the possessive attribution across two sections sufficient to make it a declared resource attribute rather than a formula intermediate, so I kept the test. It sits closer to the COMPUTED-FIELD SILENCE line than anything else in the suite.

**Final per-round pass counts** — rounds 1–8: **98/98** each (0 failed, 0 errors, 0 skipped), reproduced across two consecutive sweeps.

### Orchestrator independent verification of the green sweep

- All 8 `results.N.json` parse; each carries **98 individual test rows** (not just an aggregate), status distribution `{'passed': 98}` in every round.
- Sorted test-name lists **byte-identical to round 1 in all 8 rounds** (n=98) — no round silently collected a smaller suite.
- `app.py` mtime **06:02:26**, all 8 results **06:08:34–06:11:36** — every round ran *after* the Step-7 fix, and no impl file is newer than `results.8.json`, so the 98/98×8 result stands for the shipped code.
- `def test_` = 98 == `Design:` tags = 98; skip/xfail/skipif = 0; impl persistence grep = 0 hits.
- Post-fix `app.url_map` re-diff vs scaffold: **declared 69 / registered 69 / MISSING none / EXTRA none** — the startup rewrite did not drop a route.

## Step 8: Finalize PRD — 2026-08-04T06:15:00.000Z

**Result: zero PRD edits.** `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

### Line counts
- `PRD.md` — 554 lines
- `PRD_FINALIZED.md` — 554 lines
- Delta: **0 lines, 0.00%** (md5 `7231e3220d4bb11bd4b4eb33546676bb` on both; `cmp` clean)

### Changes
*(empty — no edits made)*

### Per-edit pre-edit search log
*(empty — no edits were committed, so no NO-NEW-MISMATCH searches were triggered)*

### Why zero edits

**What I read**
- `implementation/app.py` (all 91 lines) — the sole `<step_7_diff>` site.
- `workspace/INSTRUCTION.md` (all 53 lines) — the build/startup contract.
- `implementation/start.sh`.
- `PRD.md` — grepped for every bootstrap-adjacent term (`port`, `0.0.0.0`, `10000`, `start.sh`, `socket`, `bind`, `startup`, `boot`, `restart`, `server`, `process`, `listen`, `thread`, `concurren`, `persist`, `seed`, `in-memory`).
- Repo-wide grep over `implementation/*.py` for `__main__`, `app.run`, `threading`, `Lock`, `global`, `os.environ`.
- All 8 `results.N.json` from the final sweep.

**Why the Step 7 item carries no PRD-visible consequence**

1. **The change lives entirely inside `if __name__ == "__main__":`** (`app.py:86-90`). `create_app()` (`app.py:22-48`) — blueprint registration, the `ApiError` handler, the `HTTPException` 404/405/400/415 routing, the catch-all — is byte-for-byte untouched. No route, serializer, cascade, calculation, validation rung, or error code is in the changed region.

2. **The old and new WSGI servers are the same object.** `Flask.run()` does `options.setdefault("threaded", True)` and then calls `werkzeug.serving.run_simple`, which itself calls `make_server`. The new line calls `make_server(_host, _port, app, threaded=True, fd=...)` directly. Verified against the installed Flask 3.0.3 source: same `ThreadedWSGIServer`, same threading model, same `passthrough_errors=False`. `store.py:31`'s `threading.Lock` is unchanged and still guards the same shared state, so nothing about concurrency, OCC (`ERR_STALE_VERSION`), or the §2.9 version-check paths shifts. The only delta is *who* creates the listening socket — this process (with an `EADDRINUSE` retry loop, `app.py:70-83`) instead of Werkzeug — and Werkzeug's `fd=` path merely skips its own `server_bind`/`server_activate`.

3. **The PRD does not govern this layer.** The PRD never mentions a port, a bind address, `start.sh`, process lifetime, or restart behavior; the three grep hits for "start"/"bind" are all business prose (plan activation binding an `authorization_id`, §3 rounding). Startup mechanics are `INSTRUCTION.md`'s contract (bind `0.0.0.0`, honour `PORT`, foreground, respond within 60s) — and the new code satisfies all four exactly as the old code did, just without dying on a transient port collision.

4. **The failure mode was infrastructural, not behavioral.** The two round-1/2 errors were `"API server could not be restarted"` — the harness polling a dead port after Werkzeug's `sys.exit(1)`. No assertion about a response body, status code, field, or side effect ever failed. Consistent with the diff's own note that no test was deleted and no test failed STEP 1a or STEP 1b, and with the final sweep: **98/98 across all 8 rounds**.

Per the HARD SCOPE, every PRD edit must trace to a `<step_7_diff>` item revealing PRD-silence or PRD-mismatch. The single item is a process-bootstrap fix with no API-surface projection, so there is nothing for the PRD to pin — a fresh implementer reading `PRD_FINALIZED.md` alone still lands on a behaviorally equivalent code base. Manufacturing an edit here would have introduced exactly the kind of false claim the NO-NEW-MISMATCH rule warns Step 9 to undo.

## Step 9: Complete PRD — 2026-08-04T06:39:03.134Z

`PRD_COMPLETED.md` is written. Probe server stopped, port free.

### Result

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 554 | 554 (unchanged) |
| Words | 16,899 | 20,309 (+3,410) |
| Chars | 123,099 | 144,762 (**+21,663**) |

**67 lines revised in place.** Zero lines added or removed; headings, table rows, bullet counts and numbered-list counts are byte-identical to the source. No new sections, no new paragraphs, no new list items.

**Counts: 51 ambiguity-pins, 12 mismatch-revisions** (4 of the 12 are PRD self-contradictions — flagged separately below).

I walked all 21 modules (~4,000 lines), confirmed 69 endpoints / 24 GET / 45 POST and 29 gated writes against §2.8's list, and ran a live server to empirically verify every non-obvious claim before pinning it.

### Mismatch revisions (impl contradicts what PRD said)

- **§2.12** — revise — mismatch — "`ERR_ASSESSMENT_NOT_FOUND` regardless of what the body contains" was false: rungs 3/4 pre-empt nested-path resolution. Verified live: bad body + missing parent → `ERR_VALIDATION`/`ERR_INVALID_ENUM`; only a clean body reaches the 404 — `routes/assessments.py:121-134`, `routes/plans.py:265-268`
- **§3.4 (mastery)** — revise — mismatch — "recorded against the phase that is currently `IN_PROGRESS`" is not enforced; the delta lands on whatever phase the path names, status unchanged (verified: `LOCKED` phase accepted, 200) — `routes/plans.py:300-315`
- **§3.4 (phases)** — revise — mismatch — `sequence_index` "unique within the plan" is never checked; duplicates accepted, and the ladder resolves an index to the first-written row. Also no plan-status precondition on appending — `routes/plans.py:261-283`, `cascades.py:221-225`
- **§3.6** — revise — mismatch — plan completion writes `progress_state` = `DISCHARGE_PENDING` unconditionally, not only from `ON_TRACK`; `current_phase_index` left alone — `routes/plans.py:192-195`
- **§3.5 / §3.3** — revise — mismatch — `PLAN_SUSPENDED`/`PLAN_DISCHARGED` (cancel) and `PATIENT_DISCHARGED` (auth close) are described as cascade-only but are accepted on direct calls — `routes/sessions.py:293`, `routes/coverages.py:188`
- **§3.4 (suspend)** — revise — mismatch — same for `RED_FLAG_REFERRAL` on a manual suspend, which then behaves identically to a cascade suspension including the recall leg — `routes/plans.py:227-234`
- **§3.8** — revise — mismatch — "`source_assessment_id` pointing at the signed battery" is not enforced; status/type never inspected, not tied to the patient (verified: `DRAFT` assessment → 201) — `routes/occlusion.py:30`
- **§3.2 / §3.4 / §3.10** — revise — mismatch — `amendment_reason`, `revision_reason`, `correction_reason` are validated then discarded; no field holds them — `routes/assessments.py:224`, `routes/plans.py:204`, `routes/claims.py:297`
- **§3.10 (adjudicate)** — revise — mismatch — `ACCEPTED` does not record `denial_reason` and leaves `adjudication_variant` null; `PAID` *does* record one when supplied — `routes/claims.py:233-247`
- **§3.10 (DENIED)** — revise — mismatch — "overrides the arm's last three results" is incomplete: `deductible_applied_amount` and `coinsurance_amount` survive a denial (verified: 50.00 / 26.00 alongside zero patient responsibility) — `routes/claims.py:199-205`
- **§3.7** — revise — mismatch — the prior-reassessment and `discharge_ready` tie-breaks are write order, not `created_at` (observable only if the clock is rewound) — `store.py:162-170`
- **§2.1** — revise — mismatch — "no separate rejection is *specified*" softened the fact that none is *performed* — `auth.py:45-50`

### PRD self-contradictions (summary/§4 vs §3 detail)

Four, all now reconciled to impl:
1. **§2.12 vs the §2.7 ladder** — the strongest one: §2.12 asserted path-404 beats body validation; the ladder puts rungs 3–4 above every existence rung. The code follows the ladder.
2. **§2.11 hop 2 vs §3.11 hop 2** — §2.11 said "suspends the plan that referral names"; §3.11 correctly conditioned it on `ACTIVE`. Reconciled, and both now state it fires for directly-posted referrals.
3. **§2.11 hop 5 vs §3.11 hop 5** — §2.11 said "closes the authorizations those plans were bound to" with no status filter; impl skips anything not `ACTIVE`/`EXHAUSTED`/`EXPIRED` and de-duplicates (verified: an already-`CLOSED` pool kept its reason and version).
4. **§3.5 "the two remaining values … are written only by the cascades" vs the rung-4 enum list**, which admits all four. Rung 4 wins.

### Ambiguity pins (51) — grouped

**Envelope / global (§2.2–2.5, 13):** `api_request_timestamp` reads the logical clock (verified identical across calls); unrouted path → `ERR_REFERENCE_NOT_FOUND` 404 and bad method → `ERR_VALIDATION` 400, both pre-auth; fixed key set with nulls-not-omission, measurement the sole omitter; caller-supplied instants echoed **byte for byte** (verified `.000000Z` and `+02:00` round-trip); clock endpoint echoes `to_iso8601` verbatim and accepts backwards moves; default clock renders `2026-05-01T00:00:00.000Z`; **one version bump per row per request** regardless of write count; refused calls bump nothing except rungs 33/36; the coverage sweep bumps `version` (so a clock move can invalidate a pinned `expected_coverage_version`).

**Lists (§2.3, 5):** `created_at` asc with write-order tie-break, phase list `sequence_index`-then-same-rule; non-enum filters never existence-checked (empty page, not 404); empty-value filter treated as absent; unknown query params ignored; non-integer/empty `limit`/`offset` → `ERR_VALIDATION` (all verified live).

**Ladder (§2.7, 4):** `ciss_score` 0–60 and `coinsurance_rate` 0.00–1.00 as `ERR_VALIDATION`; the enum-routing split (membership → `ERR_INVALID_ENUM`, missing/mistyped → rung-3 `ERR_VALIDATION`); the three checks that must run after their discriminator resolves, with exact positions; no other numeric field range-checked at all.

**RBAC (§2.1, 1):** `PatientUser` single-reads 403 on another's row but the two list reads *silently narrow*, overriding a supplied `patient_id` (verified: 1 row returned, not 403).

**Clinical spine (§3.1–3.7, 17):** REASSESSMENT `plan_id` as rung-3, EVALUATION's discarded-and-unchecked `plan_id`; NPC finalize check pre-empting rungs 12/14; latest-row selection for baselines and battery booleans (verified 11 not 12, 9 not 8); `discharge_ready` recomputed only on `assessment.plan_id` (never on an EVALUATION) and lagging its own signature; cascade referral's null provider names; `weighted_minutes` 0.0 at scheduling but populated at home-log; plan version bumped on every completion/attest while the phase is bumped only on a non-zero delta; `attestation_statement` required; failed advance does not persist recomputed compliance; no-`IN_PROGRESS`-phase → `ERR_INVALID_STATE` after the plan-active gate; rung-24 skipped at the top of the ladder; no-show timing failure → `ERR_INVALID_STATE`; rung 13/14 skipped when no pool is bound; ownership-before-body on the three patient writes.

**Money & kit (§3.3, 3.9, 3.10, 11):** allowed amounts stored rounded, `coinsurance_rate` stored raw; coverage created `ACTIVE` regardless of dates; auth↔coverage, loan↔plan, claim↔session/assessment never cross-checked against the patient; `visits_authorized` 0 permitted; reauth's `new_window_end_date` unchecked against the start; serialized `quantity == 1` enforced only at fulfilment; the `REQUESTED → CANCELLED` arm still records `returned_condition`, keeps `damage_fee_amount` `0.00` and does **not** bump the item; damage-fee return date = clock's UTC date, months floored at zero; coverage bumped on **every** claim create including `EVALUATION` (verified v1→v2); session forced to `SETTLED` unconditionally; successful appeal bumps version by exactly 1 (verified v4→v5); correction does not re-adjudicate.

**Cascades (§2.11, 3.11, 5):** hop-2 fires on direct creation and its three non-firing guards; hop-5 recall skips already-`RECALLED` loans and re-runs per releasing session; `sla_breached` computed *live* on read for `SENT` rows with no write/bump (verified flipping on a clock move alone); discharge preconditions fail when the patient has no plan (verified); hop-5 dedupe + status filter.

### Verified already-pinned (negative results — the doc-generator got these right)

- **§4's 69 endpoint rows and every authorized-role list** — machine-extracted from the code and compared: exact match, including `READ_ROLES_WITH_PATIENT` on precisely the five `PatientUser`-readable GETs.
- **§2.8's write gate** — all 29 gated endpoints match the `gate_for_*` call sites exactly, and all 16 exclusions are genuinely ungated (verified: coverage create on a discharged patient → 201, second discharge → `ERR_INVALID_STATE`).
- **§5's 36 error codes and HTTP statuses** — identical to `errors.py:ERROR_HTTP`.
- **The four conservation identities** and **all 18 calculations** — waterfall step-rounding, Hofstetter/functional bands, the stepped units table, the diagnosis-forked weight sets, the occlusion ladder with its 8→7 cap, the salvage floor. Every constant matches `config.py`; no undeclared constants.
- **Room 15-min buffer vs. therapist zero-buffer**, the daily-cap row set including no-shows, and the compliance window's left-exclusive half-open rule.
- **The `therapy_indicated` amplitude term** (friction point 2) and **`patient_age_years` on occlusion** (point 6) were already correctly pinned in §3.1/§3.2/§3.8 — I only added which row is chosen when several exist.

### Orchestrator final verification

- `PRD.md` and `PRD_FINALIZED.md` byte-identical (`cmp` clean); `PRD_COMPLETED.md` = 554 lines / 20,309 words / 144,762 chars.
- Structural integrity of the Step-9 patch: **31 headings identical**, **109 table rows in both**, **67 lines changed in place**, 0 added, 0 removed.
- No implementation file is newer than `results.8.json` — the shipped code is exactly what passed 98/98 × 8.

## Pipeline complete — all 9 steps.

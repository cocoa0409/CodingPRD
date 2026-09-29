# Worklog — task_2243_point_care_testing_clia_waived

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2243_point_care_testing_clia_waived/` and `tasks/task_2243_point_care_testing_clia_waived/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T13:00:47.000Z

All three artifacts are complete and lint-clean.

## Generated: `/home/ubuntu/github/CodingPRD/tasks/task_2243_point_care_testing_clia_waived/`

**`SCAFFOLD.yaml`** (§1.0–§1.7, 3,194 lines) — scenario text verbatim; `api_prefix: /poct`
- 15 entities (flat topology): CliaCertificate, TestSite, CertificateCoverage, Operator, TrainingRecord, CompetencyAssessment, PoctDevice, QcRun, ReagentLot, StorageUnit, TemperatureReading, TestResult, PtEnrollment/PtEvent, Inspection, DeficiencyFinding
- 13 state machines (parallel shape — Operator carries independent `competency_status` × `access_status` dimensions), plus §1.2.1 with 2 optimistic-concurrency rules (`assessment-create-stale-operator`, `result-correct-stale-result`)
- 13 calculations, incl. the dual-variant `site_inspection_readiness_score` (four capped penalty terms; `AS_OF_ACTUAL` vs `PRE_SURVEY_PROJECTED`), day-of-use vs calendar QC compliance, closed-closed coverage-window overlap, PT outcome windowing, and the WAIVED-vs-MODERATE scope-creep detector
- 69 endpoints, 39 ordered validations (priority 1→69), 39 errors, 5 roles under `segregation_of_duties` (ProgramAdmin, LabDirector, QualityCoordinator, Operator, Surveyor) with four distinct SoD clauses
- `difficulty_level: beyond_expert`; layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, ops_run_checkpoint, optimistic_concurrency, derived_field_reconciliation

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8, 2,366 lines) — all 9 required rules, **26 instances** (≥2 each): dual-variant divergence, 4-term/2-cap combinatorial formula, non-linear parallel state walks, three multi-level cascades (certificate→site→operators→assessments→devices; QC failure; temperature excursion), four priority-pair conflicts, four boundary-precision checks (exact-at-bound QC value, PT score 80.00/79.99, weight thresholds 6.0/16.0), cross-entity dependencies, two temporal-overlap pairs (touching endpoints collide for coverage, are allowed for competency), and three compensating-invariant restorations.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9, 4,277 lines) — **91 instances across all 9 taxonomy sections**: 56 with full `test_recipe`, 35 `excluded_because` stubs delegating to named §1.8 instances.
- entities 12, state_machines 18, calculations 14, validations 9, endpoints 5, errors 21, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1
- Every one of the 39 error codes is triggerable by a §1.8 or §1.9 instance (two extra real instances were authored for ERR_OPERATOR_ACCESS_LOCKED and ERR_INSUFFICIENT_COMPETENCY_METHODS, which appeared in §1.8 only as preempted "NOT returned" assertions)
- `claim_type` values are drawn only from `references/claim-extraction-guide.md` rows; layers not declared in the profile (soft_delete, idempotency, bulk_operations, multi_tenancy, feature flags, pagination_with_filtering) are deliberately absent, with the reason recorded in a section comment

**Lint:** `scaffold_lint.py` → `VERDICT: clean lint` — 1,032 §1.8+§1.9 calls conform to §1.5 (endpoint declared, role allowed, payload ⊆ declared input with required present, captures resolve to declared outputs) and all §1.1 FKs are reverse-reachable.

No sibling task directory was listed, read, or searched at any point.

## Step 3: Copy shared files — 2026-09-01T13:00:47.000Z

Copied `INSTRUCTION.md` → `tasks/task_2243_point_care_testing_clia_waived/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:17:53.000Z

PRD generated at `workspace/PRD.md` — **528 lines, ~14,100 words**. The two `SCAFFOLD_*_DESIGN.yaml` files were never opened.

**Sections**

- §1 Introduction (CLIA-waived point-of-care testing oversight; derive-not-ask and logical-clock commitments)
- §2 Global Specifications: 2.1 roles/identity (entity-backed `LabDirector`/`Operator` vs opaque `ProgramAdmin`/`QualityCoordinator`/`Surveyor`), 2.2 response envelope (pasted byte-verbatim from `section-2.2-response-structure.md`), 2.3 pagination + per-collection filters + `created_at` ascending, 2.4 identity/audit fields and the logical clock (startup default exactly `2026-08-01T00:00:00Z`, `TemperatureReading`/`QcRun` carry only `id` + `created_at`), 2.5 rounding, 2.6 reference-resolution order and the five 404 families, 2.7 all 39 validation rungs in priority order, 2.8 the four segregation-of-duties clauses, 2.9 both OCC rules, 2.10 oversight posture as master gate, 2.11 derived counters + both conservation invariants + recompute-on-read, 2.12 cascade discipline and pinned walk orders
- §3 Business Logic, 9 subsections: certificates/coverage (closed-closed overlap, withdrawal cascade), sites/director, operator roster (parallel competency × access machine, half-open competency overlap), instruments/QC (failure cascade, dual rate variants, two-step index rounding), storage/temperature/lots (excursion cascade), patient results, proficiency testing (three-way grading branch), surveys/findings/weight ledger, readiness scoring + the oversight epoch's three-phase grace pass
- §4 69-row endpoint table (Method | Path | Description | Authorized Role(s)), preceded by the 201-vs-200 rule
- §5 39-row error catalogue. Document ends at §5 — no audit footer.

**Coverage audit**

Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].request_body: 84 required, 84 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
- Status: PASS (verified twice — plain-text presence, then backticked-token presence with fenced blocks stripped)

Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + `expected_operator_version`/`expected_test_result_version` + `ERR_STALE_VERSION` 412 all named), 0 missing
- state_machines[].transitions: 64 checked, 64 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing (every numeric constant in the scaffold's calculation block appears in the prose; only the literal `1.1` is absent, which is a scaffold section cross-reference, not a value)
- validations[] conditions: 39 checked, 39 matchable to `error_id` in prose, 0 missing
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing (all 69 method+path+role triples verified against the scaffold programmatically; 0 role mismatches, 0 extra/missing rows)
- entities[].fields[] structured content: 134 checked, 134 reconstructible from prose, 0 missing (all 88 enum literals present)
- sibling-branch symmetry: 11 groups checked (QC pass/fail, lot verify pass/reject, excursion release/discard, PT three-way, competency approve/reject, correction accept/reject, investigation accept/reject, posture three-way, temperature in/out of range, both compliance-rate variants, both readiness bases), 11 with equal prose density, 0 asymmetric
- Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1010
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS (also zero unbackticked occurrences of `/poct` or of any HTTP method word anywhere in §3)

Two under-specified scaffold edges were resolved by faithful reading rather than invention, and stated decisively in the prose: approving a competency assessment requires the assessment window to contain the current logical date (else `ERR_INVALID_STATE`), and a `RELEASE` excursion disposition requires every quarantined lot in the unit to carry a non-null `verified_at` (else `ERR_INVALID_STATE`). One spec conflict was also resolved: §2.3 states `created_at` ascending as the list order, which satisfies the skill's contract and cannot break tests, since the scaffold's list-ordering contract asserts only `meta` counts and set membership, never row position.

## Step 5: Generate unit tests — 2026-09-01T14:45:00.000Z

The suite is complete and fully green.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2243_point_care_testing_clia_waived/`

**Stage 1 — `test_helpers/`** (8 modules): `__init__.py`, `api_client.py` (all 69 `/poct` endpoints), `api_errors.py`, `assertions.py` (incl. `assert_logical_instant`), `constants.py`, `factories.py`, `fixtures.py` (composite setups: `setup_covered_site` → `setup_site_with_verified_lot`, `setup_temperature_excursion`, …), `test_users.py`, `types.py`.

**Stage 2 — `test_suite/`** (18 test modules + `conftest.py`): 10 queue-A files (`test_transitive_cascade.py`, `test_priority_pair_validation_conflict.py`, `test_resource_temporal_overlap.py`, `test_non_linear_state_machine.py`, `test_cross_entity_state_dependency.py`, `test_boundary_precision_check.py`, `test_combinatorial_formula.py`, `test_compensating_invariant.py`, `test_dual_variant_calc.py`) and 9 queue-B files (`test_corner_entities.py`, `test_corner_endpoints.py`, `test_corner_validations.py`, `test_corner_state_machines.py`, `test_corner_calculations.py`, `test_corner_errors.py`, `test_corner_rbac.py`, `test_corner_cross_cutting.py`, `test_corner_consistency.py`).

## Counts

- **133 tests total.** Queue A: 76 tests across all 26 non-stub §1.8 instances (every instance ≥2 tests). Queue B: 57 tests across all 56 non-stub §1.9 instances.
- **Skipped: only the 35 `excluded_because:` corner stubs.** Zero non-stub instances were dropped — every one passed the PRD-first two-condition filter.
- Audit: exactly one trailing `Design:` line per test, 0 orphan tags, 0 stub tags used, no `skip`/`skipif`/`xfail`, `pyflakes` clean over `test_suite/` (only the intentional star-re-export notices in `test_helpers/__init__.py`).

## Live verification

`prd-bench-local-run --test-dir . --start-command "python3 workspace/implementation/app.py" --isolation per-test-server` → **133/133 passed, 0 failed, 0 errors, 0 skipped** (107 s).

## Last defect resolved

`test_corner_state_machines.py::test_recording_training_advances_both_operator_dimensions_at_once` was failing `assert 'OPEN' == 'RESTRICTED'`. Root cause was in my test, not the implementation: it built its environment with `setup_site_with_operator(...)`, whose `create_trained_operator` already records training, so the "before training" site had zero locked-out operators. Rebuilt on `setup_covered_site` + untrained `create_operator`, which makes the pre-training state PRD-exact — PRD §3.2 initial state (`PENDING`/`LOCKED_OUT`/`NEVER_TRAINED`), §2.10 rule 2 strict majority (`2 × 1 > 1` → `RESTRICTED`), and §3.9 penalty 2 (gap 100 % × 0.25 = 25.00, capped at 25.0 → score 75.00) — and added those three citations to the docstring.

Two earlier failures were also mine and are fixed: version assertions on certificate suspension are now anchored on a `read_certificate` taken immediately before the suspend (coverage creation had already bumped `version`), and the factory `test_result_payload` was renamed `patient_result_payload` because its `test_` prefix made pytest collect it as a test (5 collection errors).

## Step 6: Generate implementation — 2026-09-01T14:45:00.000Z

Implementation complete and verified booting.

## Files written
All under `workspace/implementation/`:

**Launcher / infra** — `start.sh` (chmod +x), `requirements.txt` (`Flask>=2.2`), `app.py`
**Foundation** — `clock.py`, `errors.py`, `response.py`, `db.py`, `middleware.py`, `valid.py`, `serializers.py`
**Services** — `services/calc.py` (all 9 named calculations), `services/derive.py` (counters, posture, rates, CASCADE-A/B/C)
**Routes** — `routes/__init__.py` (BLUEPRINTS), `certificates.py`, `sites.py`, `operators.py`, `devices.py`, `storage.py`, `lots.py`, `qc.py`, `results.py`, `pt.py`, `inspections.py`, `ops.py`

~3,400 lines total. `python3 -m compileall` clean; `__pycache__` removed.

## Endpoint count
**69 method+path pairs registered under `/poct`, exactly matching the 69 declared in SCAFFOLD.yaml** (verified by diffing the Flask url_map against `grep -c "^  - method:"`).

## Verification performed
- Real-HTTP boot via `PORT=10099 bash start.sh` → `GET /poct/sites` returned 200 with a correct envelope.
- Full end-to-end flow through the test client: site → certificate → coverage → operators → training → director assignment → competency assessment + approval → device → storage unit → reagent lot → two-level QC → lot verification → result capture → post → correct → repost (posted_value correctly flipped 95.0 → 99.0) → inspection → finding → issue (weight 8.00, `readiness_score_at_issue` 80.00, posture RESTRICTED) → correction → segregation-of-duties rejection (422) → accept by a second surveyor → inspection auto-bubbled to CLOSED → PT enrolment → two failing shipments (second correctly tripped `UNSUCCESSFUL_LOCKED` + `UNSUCCESSFUL_PARTICIPATION` + device `QC_LOCKED/PT_UNSUCCESSFUL`) → investigation + acceptance → projected readiness (97.00 vs 94.00 actual) → temperature excursion → lot quarantine → release → certificate suspension (CASCADE-B locked all 3 operators, posture SUSPENDED) → oversight run → clock set.
- Unauthenticated request → 401 `ERR_UNAUTHENTICATED`; unknown route → 404 `ERR_RESOURCE_NOT_FOUND`.

## Notable design decisions
- **Fresh-boot safety for `--isolation per-test-server`**: `start.sh` guards pip behind `python3 -c "import flask"` so the 8 concurrent rounds don't contend on installs; `exec python3 app.py` with `use_reloader=False`, `threaded=True`, no seeding, in-memory dicts only.
- **Rank-ordered validation**: every handler follows the §2.7 priority ladder (10 site → 11 operator → 12 device → 13 lot → 14 others → 20 shape → 30 OCC → 4x status → 50 state → 52/53 operator dimensions → 54-69), not raw body order. Missing reference field → `ERR_INVALID_REQUEST`; present-but-unresolvable → that table's own 404.
- **`Decimal` + ROUND_HALF_UP throughout**; penalties rounded *before* caps; the site QC index rounds each device's day-of-use rate to a whole percent *then* averages (so 33.33 & 50.00 → 41.50).
- **`touch_if_changed`** bumps `version` only when a persisted value actually moved; explicit `db.touch` only where the PRD says "increments version" (training, reinstatement, director assignment, assessment submission, posting/correcting, investigation).
- **Device creation deliberately does not recompute compliance rates** (POST /devices is absent from the recompute-trigger list), so a new device reports 100.00/100.00; GET device, GET devices, qc-runs, test-results, qc-unlock and the oversight run do recompute.
- **Oversight run pins a Phase-0 posture snapshot before step 1**, so certificate-expiry cascades cannot feed back into the grace calculation — one pass, no fixed point.
- **Corrected values are held in a private `_corrected_value`** (never serialised) so `posted_value` stays at the previously posted figure until the correction is re-posted.
- `scope_creep_flag` is re-evaluated only at coverage creation and oversight run; `current_grace_days`/`lapse_deadline` are frozen and written only by the oversight run's Phase 1.
- Repeat-multiplier chronology uses `(created_at, insertion_seq)` so a repeat chain still works when the logical clock hasn't advanced.

## Step 7: Run tests and iterate — 2026-09-01T15:15:00.000Z

Done — 3 iterations, ending with 16 consecutive clean rounds (two full 8-round sweeps back to back).

## Summary

**Iterations run:** 3 sweeps of 8 parallel rounds each (24 rounds total, 133 tests per round).

- Sweep 1: 7/8 rounds clean; round 3 failed `test_a_scope_lock_survives_a_flawless_unlock_request` with `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))` on the `POST /poct/certificate-coverages` call at `test_corner_endpoints.py:234`.
- Sweeps 2 and 3 (after the fix): 8/8 clean each, 133/133 per round, ~180 s per round.

**Tests deleted:** none. The only failure was infrastructure-level (transport), not an assertion, so no STEP 1 coverage/derivability deletion was triggered.

**Fixes applied to `test_helpers/`:** none needed — the failing test's fixtures, headers and assertions all traced correctly to PRD §3.4/§3.9, and it passed in 7 of 8 rounds with identical setup, ruling out a fixture-precondition bug.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` (`__main__` block) — serve the Flask app through `waitress.serve(..., threads=16)` with a fallback to `app.run()` if waitress is unimportable. Root cause of the flake: Werkzeug 3.x's dev server unconditionally sends `Connection: close` on every response (keep-alive is hard-disabled in `werkzeug/serving.py`), so every API call cost a fresh TCP connection — roughly 50k connections per 8-round sweep at ~300/s, which recycles the ephemeral-port range faster than the 60 s TIME_WAIT expiry and eventually reuses a quadruple the peer answers with a RST. Waitress keeps connections alive (~1 connection per test instead of ~50), removing that failure mode.
- `workspace/implementation/requirements.txt` — added `waitress>=2.1`.
- `workspace/implementation/start.sh` — the "install only when missing" guard now checks `import flask, waitress` so the new dependency is installed on a cold environment without reintroducing per-reboot pip contention.

No behavioural change: no endpoint, response field, side effect or check was added, removed, or weakened; storage remains in-memory with nothing seeded at startup (verified by smoke test — a fresh boot reads the logical clock at exactly `2026-08-01T00:00:00Z` and holds no entities).

## Step 8: Finalize PRD — 2026-09-01T15:20:00.000Z

## Result: `PRD_FINALIZED.md` is byte-identical to `PRD.md` — zero edits, and that is the correct output.

- `PRD.md`: 528 lines. `PRD_FINALIZED.md`: 528 lines. Delta: 0 lines, 0.0%. Identical md5 (`3ebe6acd057887c66f68d516bd1cd10f`).
- Change bullets: **none.**

## Why no edit was warranted

I traced all four `<step_7_diff>` items. Each is confined to the serving/packaging layer, which the PRD does not describe at all:

1. **`app.py` `__main__` block → `waitress.serve(..., threads=16, _quiet=True)` with `app.run(...)` ImportError fallback** (`workspace/implementation/app.py:53-70`). The change lives entirely below `app = create_app()` at line 50, i.e. outside the WSGI application. Every PRD-visible surface — blueprint registration, the `ApiError` handler, the `HTTPException` handler mapping 404/405 → `ERR_RESOURCE_NOT_FOUND` and 400 → `ERR_INVALID_REQUEST`, `strict_slashes = False` — is in `create_app()` (lines 16-47) and untouched. Both the old (`threaded=True`) and new (`threads=16`) paths serve requests concurrently, so even the thread model is unchanged in kind.
2. **`requirements.txt` `waitress>=2.1`** — dependency list; no PRD counterpart.
3. **`start.sh` guard now `import flask, waitress`** — install-time only; `INSTRUCTION.md` (not PRD) owns the `start.sh` contract, and its requirements (PORT/10000, bind `0.0.0.0`, foreground `exec`) are all still met.
4. **The round-3 failure itself** — `ConnectionResetError(104)` on the transport, with no assertion touched and no test or helper edited. I read `test_suite/test_corner_endpoints.py:203-290`; every assertion is a verbatim quote of PRD §3.4 (`qc_lock_reason` of `CERTIFICATE_SCOPE` is unclearable → `ERR_INVALID_STATE` 409) and PRD §3.9 step 5 (scope-creep detection sets `QC_LOCKED` / `CERTIFICATE_SCOPE` / `scope_creep_flag`). Nothing there reveals PRD silence or mismatch.

I also confirmed the diff was genuinely limited to those three files rather than trusting the summary: `app.py`, `requirements.txt` and `start.sh` all carry the 14:53 fix-window mtime, while every business-logic module (`routes/*.py`, `services/calc.py`, `services/derive.py`, `valid.py`, `db.py`, `clock.py`, `errors.py`, `middleware.py`, `response.py`, `serializers.py`) is unmodified since 13:28-13:44, before the sweeps began.

Finally I grepped `PRD.md` for any serving-layer surface the switch could contradict (`waitress|werkzeug|flask|thread|concurren|keep-alive|connection|port|start.sh|requirements|dependenc|WSGI|server|install|framework|language|timeout|latency|performance|header|Content-Type|idempot`). The only hits are domain-level: the `X-User-ID`/`X-User-Role` header contract (§1.2), the response envelopes (§1.4), `ERR_STALE_VERSION` optimistic concurrency (§2.9), and the logical-clock startup default. That default — `2026-08-01T00:00:00Z`, never falling back to wall-clock — is already pinned twice, at PRD.md:94 and in the endpoint table at PRD.md:484, so the Step 7 smoke-test verification confirmed existing PRD text rather than exposing a gap. `grep -rn "waitress|threads|Connection|request.environ|werkzeug"` across the implementation shows waitress referenced only in `app.py`'s `__main__` block, with no request-handling code reading transport state.

## Per-edit pre-edit search log

No edits were committed, so there is no per-edit log. For completeness, the candidate subjects I evaluated and rejected:

- **(a) WSGI server / process & connection model.** (b) Enumerated and read `app.py` in full, `start.sh`, `requirements.txt`; grepped the whole implementation for transport references and the PRD for all serving-layer vocabulary. (c) No wording added — the PRD is deliberately silent on the serving layer, and any sentence naming a server, thread count, or dependency would have invented a constraint the PRD never imposed and a fresh implementer could satisfy differently without any behavioral divergence.
- **(b) Startup state: empty store + logical clock default.** (b) Enumerated `app.py:1-4` (module docstring), `clock.py`, `db.py`, and PRD.md:94 plus the endpoint-table row at PRD.md:484. (c) No wording added: the clock default is already pinned verbatim in two places, and the "nothing seeded" property was a Step 7 *verification* observation, not a fix — so pinning it would fall outside the HARD SCOPE, which admits only edits tracing to an applied fix that revealed PRD silence or mismatch.

## Step 9: Complete PRD — 2026-09-01T15:32:00.000Z

All 20 changes are pure in-place line replacements — no lines added or removed, no new sections.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`) 528 lines / 103,871 chars → `PRD_COMPLETED.md` 528 lines / 109,791 chars (**+5,920 chars**, 20 lines revised in place).

**Counts:** 12 ambiguity-pins, 8 mismatch-revisions.

### Changes

- **§2.3 Pagination/Ordering** — revise — ambiguity — `limit`/`offset` must parse as integers and `offset` may not be negative (else `ERR_INVALID_REQUEST`); equal-`created_at` ties ordered by creation sequence — `valid.py:165-190`, `db.py:67-69`
- **§2.4 Audit Fields** — revise — mismatch — recompute bumps `version`/`updated_at` only when a stored value actually moves; named the 7 writes that stamp unconditionally; listed the 8 free-text fields validated but never persisted — `db.py:82-97`, `operators.py:83,108`, `devices.py:103`, `storage.py:121`, `results.py:128`, `pt.py:200`, `inspections.py:244`, `ops.py:20`
- **§2.6 404 Family** — insert — ambiguity — unknown path or unsupported method → `ERR_RESOURCE_NOT_FOUND` 404 — `app.py:28-35`
- **§2.7 Rank 20** — insert — ambiguity — shape/interval checks precede uniqueness checks within the rung — `certificates.py:29-45`, `lots.py:27-48`
- **§2.7 Rank 60** — revise — mismatch — patient-result *posting* added: acting operator's `site_id` must equal the instrument's — `results.py:150`
- **§2.10 Posture triggers** — revise — mismatch — list expanded (operator creation, training, reinstatement, competency decision, install/retire, excursion resolution, result correction; rejected correction re-derives nothing) — `operators.py:52,99,124,272`, `devices.py:70,164`, `storage.py:150`, `results.py:205`, `inspections.py:270`
- **§2.11 Recompute-on-read** — revise — ambiguity — site/readiness reads first refresh every instrument at the site (rates + `use_day_count` + schedule); instrument-collection read refreshes the whole inventory, not just the page/filters — `sites.py:58,102`, `devices.py:84-85`, `derive.py:88-105`
- **§2.12 Cascade Ordering** — insert — ambiguity — all orderings and strict-chronology comparisons break `created_at` ties by creation sequence — `db.py:100-106`, `derive.py:17-38`
- **§3.1 Coverage creation** — insert — ambiguity — exact `scope_creep_flag` rule (non-retired MODERATE instrument under WAIVED in-window coverage) and that only coverage creation can clear it — `derive.py:163-172`
- **§3.3 Approval** — revise — mismatch — subject's prior `competency_status` is not a precondition; set to `COMPETENT` regardless — `operators.py:256`
- **§3.3 Rejection** — revise — mismatch — revocation at count "2 or more", from whatever competency value held — `operators.py:266-269`
- **§3.4 QC unlock** — insert — ambiguity — non-`PASS` confirming run → rank-50 `ERR_INVALID_STATE`, ahead of the rank-61 device-mismatch test — `devices.py:114-118`
- **§3.4 Compliance window** — insert — ambiguity — rewound clock giving an empty window → both rates 100.00, `use_day_count` 0 — `calc.py:100-102`
- **§3.4 Site index** — insert — ambiguity — index reads each instrument's *persisted* day-of-use rate — `calc.py:164-173`
- **§3.6 Capture** — insert — ambiguity — analyte mismatch is a rank-50 `ERR_INVALID_STATE` — `results.py:46-49`
- **§3.9 Readiness read** — insert — ambiguity — a `basis` outside the two names → `ERR_INVALID_REQUEST`, after site resolution; empty means default — `sites.py:97-100`
- **§3.9 Readiness triggers** — revise — mismatch — list expanded (posting/correcting a result, coverage creation, QC unlock, excursion open/resolve; rejected correction excluded) — same call sites as §2.10
- **§3.9 Scope creep (item 5)** — insert — mismatch — flag only ever raised here, never cleared, and only when an instrument was actually locked this pass — `ops.py:124-146`
- **§3.9 Run summary** — insert — ambiguity — defined `operators_locked_out`, `devices_qc_locked`, `scope_creep_sites`, `sites_posture_changed` as whole-pass sums against the phase-0 snapshot; `evaluated_at` equals each site's `last_oversight_run_at` — `ops.py:25-33,106-155`
- **§3.9 Phase 0** — revise — ambiguity — snapshot taken before item 1 (certificate expiry), not merely before the grace pass; same snapshot backs `sites_posture_changed` — `ops.py:35-37`

**Verified-consistent (no change needed):** all 60 endpoint paths, methods, status codes and role lists; validation-precedence order at every write; the three named cascades; both overlap geometries; all rounding orders (`round0`-then-average for the site index, penalty-round-then-cap for readiness); the three-shipment PT window ordering; error-catalogue IDs and HTTP statuses.

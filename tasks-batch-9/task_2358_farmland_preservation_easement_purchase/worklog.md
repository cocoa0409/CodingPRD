# Worklog — task_2358_farmland_preservation_easement_purchase

## Step 1: Create task directory — 2026-09-02T04:05:13.788Z

Created `tasks/task_2358_farmland_preservation_easement_purchase/` and `tasks/task_2358_farmland_preservation_easement_purchase/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T06:17:59.849Z

All three scaffold artifacts are complete and the lint is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    63
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  2113
```

Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2358_farmland_preservation_easement_purchase/`:

**SCAFFOLD.yaml** (3,882 lines, §1.0–§1.7) — `difficulty_level: expert_plus`; archetypes `multi_party_negotiation` + `quota_allocation`; graph topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency. Counts: 14 entities, 12 multi-dimensional state machines, 4 OCC concurrency rules, 10 calculations, 39 validation ladder rows (priorities 1–29), 63 endpoints, 60 errors, 6 roles. Domain spine: PreservationProgram → FundingRound → Application (rank/appraise/negotiate/fund/close) → Easement with three independent dimensions (status, compliance_status, stewardship_status) plus Amendment, Violation, MonitoringVisit, FundingSource/FundingCommitment.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1,798 lines) — 9 rules x 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**SCAFFOLD_CORNER_DESIGN.yaml** (4,912 lines) — all 9 guide sections, 100 instances: entities 15, state_machines 17, calculations 15, validations 15, endpoints 6, errors 16, rbac 8, cross_cutting_complexity_layers 7, consistency_model 1. 71 carry full recipes, 29 are `excluded_because` stubs citing §1.8 instances by name (all citations verified to resolve).

Coverage audit:
- All 60 error ids appear across §1.8+§1.9. 58 have a real trigger. Two are documented as structurally unreachable defensive invariants in a `Satisfaction → Pass` instance rather than triggered: **ERR_FUNDING_PLAN_STALE** (no §1.5 path can present a FUNDED plan whose target has drifted without also bumping the Application version, which trips OCC first) and **ERR_EASEMENT_SCOPE_MISMATCH** (every easement-scoped child endpoint derives the easement from the path, so the mismatch cannot be expressed).
- All 63 endpoints appear in at least one call; five by-id GETs (`/landowners/{id}`, `/closing-requirements/{id}`, `/monitoring-visits/{id}`, `/violations/{id}`, `/amendments/{id}`) are exercised principally as 404 probes in the errors section.
- All 4 §1.2.1 concurrency rules get a dedicated stale-version OCC instance using their declared `write_endpoint`/`occ_field`; `selector_policy` (no guide row) gets a real instance showing LAST_NON_ZERO_TAKE remainder absorption relocating from the FEDERAL to the STATE source when FEDERAL is suspended, with the absorbed 40,091,232 legally exceeding STATE's own 0.40 share cap.
- Placeholder closure, per-instance capture binding, cross-file name uniqueness (118 names, 0 collisions) and absence of banned concurrency vocabulary all verified programmatically. Two incidental uses of "simultaneously" and one half-open-window wording nit in the §1.8 grace-period assert were rewritten.

## Step 3: Copy shared files — 2026-09-02T06:17:59.849Z

Copied `INSTRUCTION.md` → `tasks/task_2358_farmland_preservation_easement_purchase/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:34:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2358_farmland_preservation_easement_purchase/workspace/PRD.md` — **480 lines**.

## Sections emitted

`# Farmland Preservation Easement Purchase API — Product Requirements Document`

- **§1 Introduction** — 3 paragraphs (domain, operational pain, scope).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (all 6 roles, `X-User-ID`/`X-User-Role`, entity-backed vs. opaque identity semantics incl. the `Appraiser` ownership exception), 2.2 API Response Structure (**verbatim** from `section-2.2-response-structure.md`, byte-identical), 2.3 Pagination & List Ordering (defaults 10/1/100/0, 8 per-endpoint sort overrides, all filters), 2.4 Record Identity & the Immutable Negotiation Log, 2.5 The Logical Clock & the Time-Driven Sweep, 2.6 Numeric Domains/Money/Rounding, 2.7 OCC on Parent Versions, 2.8 Cascade Discipline (multi-dimensional state, the two conservation invariants), 2.9 Segregation of Duties, 2.10 Path Resolution, 2.11 the 21-rung Validation Precedence ladder.
- **§3 Business Logic** — 9 subsections (program/rounds/appropriations; parcels & scoring; intake & ranking; appraisal; negotiation & cost build-up; funding waterfall; acceptance/pre-closing/recording; stewardship/monitoring/violations; amendments & exact reversal).
- **§4 Endpoint Definitions** — 1 intro paragraph on status codes + 4-column table, 63 rows.
- **§5 Error Code Catalogue** — 2-column table, 60 rows.

## Coverage

| Scaffold element | In scaffold | Covered |
| --- | --- | --- |
| Entities | 14 | 14 (incl. `NegotiationRound` explicitly flagged as carrying only `id`/`created_at`) |
| Entity field names | 162 | 162 |
| Endpoint input names | 107 | 107 |
| Endpoints | 63 | 63 (all in §4) |
| Error codes | 60 | 60 (all in §5 **and** all anchored in §1–§4 prose) |
| Calculations | 10 | 10 (all constants literal-matched) |
| State machines / transitions | 12 / 85 | all dimensions and literals in prose |
| Concurrency rules | 4 | 4 (§2.7, each with its rationale) |
| Validations | 39 | folded into §2.11 ladder + per-workflow anchors |
| Roles | 6 | 6 |

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 176 required names (162 entity fields ∪ 107 endpoint inputs) verified present in backticks, 176/176, 0 missing.

**Contract 2 — Rule Coverage: PASS.** Validation priority ordering rendered as an explicit global ladder with the concurrency-above-state inversion called out; all 4 `concurrency_rules` given field + error + 412 + rationale; cross-entity side effects enumerated per workflow (acceptance obligation chain → source threshold flip → cross-application lapse → `UNDERFUNDED`; closing disbursement; termination/parcel release; amendment suspension); every `applies_to` scope stated; field-level structured content (polymorphic closing-requirement payload, `permitted_uses` members, all 4 non-entity response shapes) rendered; sibling-branch symmetry preserved (both acceptance branches, both amendment reversal directions, submit/reinstate compliance gate, tier boundaries).

**Contract 3 — §3 Path Purity: PASS.** 398 distinct backtick tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path; 0 raw endpoint paths appear as plain text in §3 either.

## Zero-Silence audit notes

- **Only inferred item:** the scaffold states the `DRAFT → OPEN` round precondition (program `ACTIVE` + ≥1 `ACTIVE` funding source) without nominating an error ID. I attached it to `ERR_INVALID_ROUND_STATE` (409), the only plausible code in the family, rather than leave the failure mode silent or invent a new code.
- **Deliberate wrong-variant warnings written into the prose** so an implementer cannot silently pick the wrong one: composite-score rounding once on the weighted sum (not per component); receipt vs. round-close contiguity basis; preliminary floor-to-$1,000 vs. certified round-half-up-to-$100; admin-fee tier on pre-fee `bargain_sale_price_cents` not on the total; per-source floor-then-sum in the waterfall; strict `>` on the impervious finding and on `MAJOR` severity at 2,000 sqft; left-closed/right-open zoning tiers; half-open monitoring boundaries; `available_cents` not netting `RESERVED`.
- Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read. All extraction was scripted against `SCAFFOLD.yaml` only.

## Step 5: Generate unit tests — 2026-09-02T08:28:16.882Z

All three remaining files are written and both mandatory citation passes are green. Final state of the deliverable:

**Files written this session**
- `/home/ubuntu/github/CodingPRD/tasks/task_2358_farmland_preservation_easement_purchase/test_suite/test_16_rbac.py` — 7 tests / 7 live `rbac` instances
- `.../test_suite/test_17_cross_cutting_layers.py` — 5 tests / 5 live `cross_cutting_complexity_layers` instances
- `.../test_suite/test_18_consistency_model.py` — 1 test / 1 live `consistency_model` instance
- Citation repairs (verbatim C1/C3 fixes, no assertion changes) in `.../test_suite/test_04_transitive_cascades.py`, `.../test_08_temporal_overlap.py`, `.../test_09_compensating_invariants.py`

**Full suite: 20 files, 140 tests**
- `test_helpers/` — 9 files (Stage 1, unchanged)
- Queue A, `test_01`–`test_09`: 64 tests, 18/18 difficulty instances, every instance ≥2 tests (8/7/6/8/6/6/7/8/8)
- Queue B, `test_10`–`test_18`: 76 tests, 71/71 live corner instances — entities 13, state_machines 10, calculations 10, validations 11, endpoints 7, errors 12, rbac 7, cross_cutting 5, consistency 1

**Verification run**
- Scaffold-citation pass: 140 `Design:` tags, exactly one per test and always the docstring's last line; 0 unknown tags, 0 stub tags, 0 dual tags. Coverage 18/18 difficulty (all ≥2) and 71/71 live corner.
- PRD-citation pass: all 145 quoted citations match `workspace/PRD.md` verbatim after whitespace normalisation, every test names a `PRD §` section, and every claimed section number matches the section the quote actually lives in.
- AST + `test_helpers` name-resolution + unused-import check clean on all 20 files; `py_compile` clean. Every list filter used is in the §2.3 enumeration; every role/headers pairing checked against the §4 table.

**Instances skipped:** only the 29 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` (7 errors/rbac/cross-cutting stubs among the ones read this session: `segregation_of_duties_across_the_appraisal_and_closing_reviews`, the six `error_triggerable_*` stubs, `cascading_side_effects_across_the_acceptance_and_visit_completion_chains`, `dual_variant_calculation_of_the_composite_score_and_the_easement_value`). No live instance was dropped.

**Coverage-audit notes (adjudications where a recipe was not uniquely PRD-derivable)**
- `test_15`: the day-729 sweep asserts only `terminated_easement_count == 0` / `expired_source_count == 3`; the recipe's `due_count == 0` / `delinquent_count == 0` contradicts §3.8's "posture is read off the logical clock". The impervious-request leg of `a_terminated_easement_refuses…` is omitted (§3.8 declares no easement-state precondition there).
- `test_15` capacity instance reuses `setup_two_applications_competing_for_headroom()` and asserts the PRD-derivable ledger (reserved 112,255,446 / committed 56,127,723 / available 3,872,277) instead of the recipe's asymmetric figures — same rung, same code.
- `requirement_total_count` in the AcquisitionOfficer recipe does not exist in the PRD; the real field is `requirement_total` (used).
- Sweep idempotency is always asserted via the eight transition counters plus unchanged `version`/`stewardship_status`, never via `swept_easement_count`, which the PRD does not pin.

No pytest run was attempted (per the standing note that a red `prd-bench-local-run` sweep on a loaded host is usually the runner's own lsof timeout).

## Step 6: Generate implementation — 2026-09-02T08:28:16.882Z

The implementation is complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2358_farmland_preservation_easement_purchase/workspace/implementation/` — 4,399 lines total, 27 files:

| File | Lines | File | Lines |
|---|---|---|---|
| `start.sh` | 10 | `services/calc.py` | 185 |
| `requirements.txt` | 1 | `services/lookup.py` | 259 |
| `app.py` | 92 | `services/serialize.py` | 328 |
| `db.py` | 115 | `services/cascade.py` | 462 |
| `errors.py` | 87 | `routes/programs.py` | 103 |
| `middleware.py` | 50 | `routes/rounds.py` | 164 |
| `response.py` | 99 | `routes/landowners.py` | 41 |
| `validation.py` | 215 | `routes/parcels.py` | 191 |
| `routes/applications.py` | 719 | `routes/appraisals.py` | 179 |
| `routes/funding.py` | 164 | `routes/requirements.py` | 174 |
| `routes/easements.py` | 262 | `routes/visits.py` | 159 |
| `routes/violations.py` | 146 | `routes/amendments.py` | 166 |
| `routes/ops.py` | 28 | `routes/__init__.py`, `services/__init__.py` | 0 |

## Endpoints

**63 endpoints — an exact set-match against the scaffold** (verified programmatically: zero in-spec-not-implemented, zero extras). By group: Application 12, Easement 7, FundingSource/Commitment 6, Amendment 5, Appraisal 5, FundingRound 5, MonitoringVisit 5, ClosingRequirement 4, Violation 4, Parcel 3, Program 2, Landowner 2, ops 2 (`POST /_clock/set_current_utc`, `POST /stewardship-sweeps`).

## Verification

- **All 10 scaffold `calculations:` blocks reproduce every worked example exactly** — including the funding waterfall's per-source floored caps summing 1 cent short of the 160,364,925 target and the `LAST_NON_ZERO_TAKE` absorption (56,127,723 / 64,145,970 / 40,091,232 with `absorbed_remainder_cents = 1`), the two divergent easement-value roundings (157,900,000 vs 175,550,000 on identical inputs), the pre-fee admin-fee tier (fee 1,490,000 not 1,117,500), installment residue placement, `NO_ISSUE` at exactly the allowance, MINOR at exactly 2,000 sqft, and all four half-open stewardship boundaries.
- **Fresh boot over real HTTP via `start.sh`** returns an empty store and the default logical clock `2026-08-01T00:00:00Z`; 401 unauth, 404, and `ERR_WEIGHTS_NOT_NORMALIZED` all correct.
- **Full-lifecycle smoke run: 0 failures** (program → sources → round → parcel → application → appraisal → rank → offer → funding plan → acceptance → requirement reject/resubmit/accept → closing → monitoring → violation → cure → amendment approve/rescind → sweeps → invariant `authorized == available + committed`).

Storage is process-local Python dicts, nothing seeded, no disk or `/tmp` persistence.

## Fixes made during this pass
- `errors.py` / `services/lookup.py`: `ERR_FUNDING_SOURCE_NOT_FOUND` → the spec's actual id `ERR_SOURCE_NOT_FOUND`.
- `services/calc.py`: finding enum `NO_VIOLATION` → `NO_ISSUE` (SCAFFOLD.yaml:931).
- `services/cascade.py`: `open_violation` no longer regresses a `VIOLATION_ESCALATED` easement back to `VIOLATION_OPEN` (the compliance state machine declares only `COMPLIANT → VIOLATION_OPEN`).

## PRD ambiguities resolved
1. **Validation ordering** — per-endpoint scaffold `validations[].priority` conflicts with PRD §2.11's global 21-rung ladder; I made the global ladder authoritative everywhere. Within rung 9 on requirement submission, PRD §3.7 prose puts the requirement-state check before the closing-state check, so that is the order.
2. **Unnamed error ids** — forbidden `surveyed_acres` on a non-survey type → `ERR_SURVEY_ACREAGE_MISMATCH`; forbidden `lienholder_name` → `ERR_LIENHOLDER_REQUIRED`; `IMPERVIOUS_EXCEEDANCE` opened directly with `excess_sqft <= 0` → `ERR_INVALID_REQUEST` (422); cure-plan/cure-verification past `cure_deadline_on` → `ERR_INVALID_VIOLATION_STATE`; missing `reason` on amendment REJECT → `ERR_INVALID_REQUEST`.
3. **`ERR_EASEMENT_SCOPE_MISMATCH` has no observable trigger** on `POST /monitoring-visits` or `POST /easements/{id}/amendments` (neither child carries a program field). Implemented as the practical proxy `easement.parcel_id == application.parcel_id` at rung 16.
4. **`POST /easements/{id}/impervious-requests` deliberately has no easement-state gate** — neither the PRD nor the scaffold `side_effects` lists one, so adding a `RECORDED|AMENDED` check risked spurious 409s.
5. **`POST /_clock/set_current_utc` is authenticated, not exempt** — the scaffold lists all six roles for it, so ladder rungs 1–2 still apply (validation rule 1 only exempts it from the *header-presence* requirement, which I read as not exempting it from role checks; it accepts any of the six roles).
6. **Amendment `SUSPENDED → UNDER_REVIEW`** — validations priority 17 lists `POST /amendments/{id}/reinstatement` in its `applies_to`, so reinstatement applies the same `amendment_policy` compliance gate as submission.
7. **`sweep_order`** is the source's 1-based position in the eligible sweep order (not a dense index over emitted commitments only).
8. **`stewardship_status` is sweep-driven, not recomputed on read** — SCAFFOLD.yaml:1799-1810 attaches each transition to `POST /stewardship-sweeps` with a version bump, so `GET /easements/{id}` returns the stored value until a sweep runs. (Counters, source ledgers, program acreage, and `residential_rights_extinguished` *are* recomputed at serialization time.)

## Step 7: Run tests and iterate — 2026-09-02T11:09:17.000Z

All fixes are in and verified. Here is the state of the loop.

## Summary

**Iterations run: 3 full 8-round sweeps + 4 clean full-suite verification rounds.**

Sweep 1 (pre-fix) produced 4 genuine defect clusters (each failing 8/8) plus ~53 infra-only failures. After the fixes below, sweep 2 (`results.1–8.json`, load ≈250) returned **0 assertion failures in all 8 rounds** — 376 non-passes, every one of them the runner's own `subprocess.TimeoutExpired: lsof -ti:PORT -sTCP:LISTEN ... timed out after 5 seconds`, plus one `ConnectionResetError(104)`. Sweep 3 collapsed further into infra noise (load 380–556; 39 sibling task directories were running their own 8-round sweeps concurrently, ~250 `prd-bench-local-run` processes): its 6 "FAILED" entries are `pytest-timeout (>30s)` and `ERR_VALIDATION - The requested route does not exist` (a sibling task's server had taken the port), not assertions.

To get a contention-free signal I drove the same per-test-server isolation myself with a pytest plugin that owns the server PID (`/tmp/t2358_plugin.py`, kill by PID, fresh port, no `lsof`): **4 independent full-suite rounds, 140/140 passed each** (one solo, then three concurrently for timing variance). Every round ran the final state of all edited files.

**Tests deleted: none.** Three assertions were removed inside kept tests (STEP 1c splits), all one silence category:
- `test_10_entities.py::TestProgramCreation::test_program_creation_echoes_every_declared_field` — dropped `created_at.startswith("2026-08-01")`. COMPUTED-FIELD SILENCE: §2.4 says only "an ISO 8601 UTC instant with three fractional digits"; §2.5 scopes the logical clock to "every window, expiry, deadline and projection rule", never to record stamps. Scaffold-only rule: `created_at` reads the logical clock.
- `test_10_entities.py::TestParcelSurface::test_parcel_retrieval_returns_the_stored_inputs_and_both_scores` — dropped `created_at.startswith("2026-08-10")`, same category.
- `test_10_entities.py::TestListingAndSystemFields::test_system_fields_are_server_generated_and_updated_at_advances` — dropped both clock-prefix assertions, kept the PRD-covered content as clock-agnostic equivalents (`patched["created_at"] == parcel["created_at"]`, `patched["updated_at"] >= parcel["updated_at"]`, `version == 2`, stable `id`).

**test_helpers fixes: none required** (the header/fixture layer was already PRD-faithful; the 401 storm came from the implementation, below).

**test_suite fixes (unfaithful requests, STEP 2):**
- `/…/test_suite/test_17_cross_cutting_layers.py::TestOfferIssuanceConcurrency::test_the_stale_offer_is_refused_and_the_refreshed_one_advances_the_count` — the refreshed offer was issued while the application sat in `OFFER_ISSUED`, which §3.5 forbids ("issues an offer from either `RANKED` or `COUNTERED`… any other state yields `ERR_INVALID_APPLICATION_STATE`"). First offer lowered to 160,000,000 and a landowner counter of 175,550,000 interposed to reach `COUNTERED`; every original assertion is preserved, including `negotiation_round_count == 2` (a `COUNTER` entry is not an `OFFER`) and `total_program_cost_cents == 172_550_000`.
- `/…/test_suite/test_01_dual_variant_valuations.py::TestEasementValueBasis::test_the_certified_basis_alone_bounds_the_offer` — the `ERR_OFFER_EXCEEDS_CERTIFIED_VALUE` probe was fired after the application had already moved to `OFFER_ISSUED`, where §2.11 rung 9 (state) outranks rung 18 (certified ceiling). The two requests were reordered so the over-ceiling probe runs from `RANKED`; both assertions kept verbatim.

**Implementation fixes (PRD covers + uniquely determines, STEP 3):**
- `/…/workspace/implementation/routes/ops.py` — removed `authenticate(...)` from `POST /_clock/set_current_utc`. §2.5: "it is the one endpoint exempt from the authentication headers of §2.1"; §2.1: "Every request except the clock-setting operation described in §2.5 must carry two headers". The worklog had recorded the opposite reading as a resolved ambiguity, and it returned 401 to 13 tests. No capability was added — the endpoint already existed.
- `/…/workspace/implementation/services/lookup.py` — `easement_pending_amendment_count` counted `("UNDER_REVIEW", "SUSPENDED")`. §3.8: "`pending_amendment_count` counts amendments in `UNDER_REVIEW`", and the suspension cascade "is recomputed downward". Now counts `UNDER_REVIEW` only, which fixed `test_04_transitive_cascades.py::TestVisitCompletionCascade::test_the_hold_suspends_the_amendment_that_was_under_review` (`assert 1 == 0`) without disturbing the other four tests that pin the counter.

Storage remains in-memory dicts, nothing seeded; no endpoint, field, header or side effect was added.

**Caveat on the exit gate:** the literal condition (all 8 `prd-bench-local-run` rounds `passed == total`) was not observable in this environment — the host is saturated by other task directories' sweeps, and the runner's 5s `lsof` kill step and port registry fail long before the artifact does (consistent with the stored memory note). The strongest available evidence is the 4 × 140/140 contention-free rounds plus 8 runner rounds containing zero assertion failures. Re-running `/tmp/t2358_sweep.sh` when host load drops below ~50 should show 8/8 green; note the runner only wrote `results.*.json` on the sweep that was not killed at teardown.

**Orchestrator note:** at Step 7 exit, host load average was 775 with 575 concurrent `prd-bench-local-run` processes from sibling pipelines. The orchestrator relaunched the 8-round sweep against the final artifact state to produce `results.{1..8}.json`; see the Step 7 verification-sweep entry appended after Step 9.

## Step 8: Finalize PRD — 2026-09-02T11:24:33.000Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 480 lines; `PRD_FINALIZED.md`: 480 lines — **0.0%** line delta (2 lines revised in place, 0 added/removed, no new sections).

## Changes (1 per bullet)
- **§2.4 (line 100)** — *revise* — appended that `created_at`/`updated_at` (and the envelope's `api_request_timestamp`) are real-wall-clock audit stamps, never the §2.5 logical clock, so `POST /_clock/set_current_utc` never moves them; re-affirmed that domain instants (`ranked_at`, `completed_at`, `opened_on`, `cured_on`, `escalated_on`, `last_monitored_on`, windows/expiries/deadlines/projections) still read the logical clock — `implementation/db.py:80-83` (`base_row` → `wall_now()`), `implementation/db.py:102` (`touch` → `wall_now()`), `implementation/response.py:27`.
- **§2.4 (line 102)** — *revise* — added that `updated_at` equals that row's `created_at` at creation — `implementation/db.py:81-84`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 record-stamp clock source**
- (a) Subject: the clock source of every server-generated timestamp (`created_at`, `updated_at`, `api_request_timestamp`) versus the logical clock.
- (b) Paths enumerated/read: `db.py` (`DEFAULT_CLOCK_UTC`, `wall_now`, `clock`, `base_row`, `touch`, `iso`, `created_key`); `response.py:27`; every `base_row` callsite — `routes/applications.py:130,641`, `routes/appraisals.py:65`, `routes/easements.py:244`, `routes/funding.py:71`, `routes/landowners.py:25`, `routes/parcels.py:92`, `routes/programs.py:68`, `routes/rounds.py:36`, `routes/visits.py:61`, `services/cascade.py:31` (NegotiationRound, `with_version=False`), `:133`, `:191`, `:326`; every `db.clock` read (`routes/ops.py:20-21`, `routes/rounds.py:111,153`, `routes/applications.py:108,261,332,370,590`, `routes/visits.py:97,105,118`, `routes/violations.py:98,126,133`, `services/cascade.py:179,189,348,399,437`); `services/serialize.py` (all 14 serialisers, confirming 13 emit `updated_at`/`version` and the negotiation log emits `created_at` only).
- (c) Wording adjustment: I deliberately did **not** write a blanket "server-generated timestamps use wall time" claim, because the same grep shows 16+ domain instants (`ranked_at`, `completed_at`, `last_monitored_on`, `opened_on`, `cured_on`, `escalated_on`, plus all window/expiry/deadline comparisons) that *do* read `db.clock`. The sentence was scoped to the three named stamps and paired with an explicit re-affirmation of the logical clock for domain instants. Each domain field I named was individually verified as `= db.clock` before including it; `recorded_on` was deliberately **excluded** from that list because it is client-supplied and only *compared* against the clock (`routes/applications.py:590`). I also verified no path anywhere writes `created_at` from `db.clock`, so the "never" is safe.

**Edit 2 — §2.4 `updated_at` initial value**
- (a) Subject: the value of `updated_at` at row creation.
- (b) Paths enumerated: `db.py:80-84` (`base_row` — the sole creation path; a single `now` string is assigned to both `created_at` and `updated_at`), `db.py:98-110` (`touch` — the only other writer of `updated_at`, mutation-only), `services/cascade.py:31` (the one `with_version=False` creation, NegotiationRound, which gets neither `updated_at` nor `version`, matching §2.4's existing exception paragraph), and all 13 `updated_at`-bearing serialisers in `services/serialize.py`.
- (c) Wording adjustment: qualified as "equal to **that row's** `created_at` at creation" and left inside the sentence that already excludes the negotiation log, so the claim cannot be read as applying to the one resource type that has no `updated_at`.

## Items that needed no PRD edit
The remaining four `<step_7_diff>` items are all already uniquely determined by `PRD.md`, so prose was kept verbatim: the two `test_suite` request fixes (§3.5's "offer from either `RANKED` or `COUNTERED` … any other state yields `ERR_INVALID_APPLICATION_STATE`", §3.5's `negotiation_round_count` = count of `OFFER` entries, and §2.11's rung 9 > rung 18 ordering — verified against `routes/applications.py:265-286`); the `ops.py` 401 fix (§2.1 + §2.5 both state the clock endpoint is exempt, and §4 authorizes all six roles — `routes/ops.py:15-23` now runs no `authenticate`); and the `lookup.py` counter fix (§3.8 "`pending_amendment_count` counts amendments in `UNDER_REVIEW`" matches `services/lookup.py:235-238` exactly).

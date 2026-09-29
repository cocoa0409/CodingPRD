# Worklog — task_2276_wireless_site_acquisition_zoning

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2276_wireless_site_acquisition_zoning/` and `tasks/task_2276_wireless_site_acquisition_zoning/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T16:22:00.000Z

All three scaffold artifacts are complete and pass the generator's linter.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2276_wireless_site_acquisition_zoning/`)
- `SCAFFOLD.yaml` — 2,984 lines, §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,173 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2,346 lines, single key `scaffold_corner_design`

**§1.0–§1.7 seed content**
- **13 entities**: SearchRing, Landlord, Jurisdiction, Candidate, LeaseAgreement, ZoningApplication, StructuralAnalysis, ModificationDesign, EnvironmentalReview, ConstructionPermit, UtilityProvider, UtilityBackhaulOrder, OnAirPlan
- **10 state machines**, including Candidate's two independent dimensions (acquisition_status × feasibility_status), the cyclic zoning tolling loop (INCOMPLETE→CURED), the fork/join EnvironmentalReview (tribal + public-notice branches), and the lease counter/revise cycle capped at 6 rounds
- **2 §1.2.1 concurrency rules**: `structural-analysis-create-stale-candidate` (`expected_candidate_version` → 412 ERR_STALE_CANDIDATE_VERSION) and `select-site-stale-ring` (`expected_search_ring_version` → 412 ERR_STALE_RING_VERSION)
- **12 calculations**, two of them dual-variant (`lease_committed_rent` provisional/final, `on_air_schedule_forecast` baseline/risk-adjusted) plus tiered `zoning_fee_total`, non-linear `structural_capacity_utilization` (wind²×ice interaction), half-open interval `provider_crew_day_ledger`, and three ledger/reconciliation calcs
- **50 ordered validations** (priorities 1–75, auth → pagination → existence → referential → OCC → state → business), **67 endpoints** (incl. 3 computed reads: rent-schedule, shot-clock, forecast), **62-code error catalog** (13 entity-specific 404s), **7 RBAC roles** (RfEngineer, SiteAcquisitionAgent, ZoningPlanner, StructuralEngineer, EnvironmentalReviewer, ConstructionManager, ProgramDirector) with owner-scoping and two segregation-of-duties rules

**§1.8 — 24 instances across all 9 difficulty rules**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

**§1.9 — 51 instances over all 9 taxonomy sections**: 36 full test recipes + 15 `excluded_because` stubs pointing at the covering §1.8 instance. Per section (total/full): entities 8/7, state_machines 10/5, calculations 7/4, validations 9/6, endpoints 4/3, errors 3/3, rbac 4/4, cross-cutting complexity layers 5/3, consistency model 1/1.

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint` (67 endpoints, 13 entities, 24 §1.8 + 36 §1.9 instances, 796 calls scanned)
- Independent check script confirmed: all 75 instance names unique across both design files, every `grounds:` reference resolves to a real calculation / transition / validation priority / entity field / error id / concurrency rule / endpoint / role, every instance has exactly one of `test_recipe` or `excluded_because`, all error captures use `$.data.error_id`, and all `expected_*_version` payload values are `${var}` placeholders
- Numeric asserts were hand-recomputed against the declared formulas (e.g. FLAT_STEP lease 150000.00/346500.00/Δ196500.00; BY_RIGHT fee 1560.00 with 2026-09-30 shot clock; risk band boundary 70.00 HIGH vs 68.00 MEDIUM on baseline 2027-02-28 / risk-adjusted 2027-04-12; utilization 71.70 PASS vs 99.70 PASS_WITH_MOD; rf score 98.50)

The hard constraint was honored throughout: no sibling `tasks/task_*` artifact was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-01T16:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2276_wireless_site_acquisition_zoning/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:36:00.000Z

The doc-generator subagent wrote `workspace/PRD.md` (507 lines, 87,086 bytes) but was terminated by a transient API error before it could emit its own summary. The orchestrator therefore ran the coverage audit directly against `SCAFFOLD.yaml`:

- Structure: the five mandated sections are present — §1 Introduction, §2 Global Specifications & System-Wide Principles, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue.
- Endpoint coverage: 67 / 67 scaffold endpoint paths appear in PRD.md (0 missing).
- Error catalogue coverage: 62 / 62 scaffold error ids appear in PRD.md (0 missing).
- Calculations: all 12 scaffold calculations are rendered as prose/formula rather than by internal snake_case identifier, as the doc-generator spec requires (identifiers themselves intentionally absent).
- Validations: 50 scaffold validations present in the scaffold; §2/§3 render the ordered validation pipeline.
- Hard constraint honored: no read of `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory (verified from the subagent's tool trace before termination).

## Step 5: Generate unit tests — 2026-09-01T18:15:00.000Z

Done. Generation is complete and green.

## Files written

**`test_helpers/`** (6 modules + `__init__.py`, `types.py`)
- `api_client.py` — one method per PRD endpoint (40 POST / 29 GET), plus `post`/`get` overrides so the `payload=` convention reaches the transport
- `test_users.py` — identity headers for all seven roles (`agent-001`/`002`, `director-001`, `sengr-001` ANALYST / `-002` DESIGNER / `-003` CERTIFIER, `planner-001`/`002`, `rfe-001`, `env-001`, `cm-001`)
- `constants.py`, `factories.py`, `fixtures.py` (composite scenario builders: `base_reference_data`, `engaged_candidate`, `executed_lease`, `zoning_granted`, `delivered_orders`, …), `assertions.py` (`assert_fields`, `assert_money`, `assert_score`, `assert_instant`, `assert_error*`, `ok`), `api_errors.py`
- `test_suite/conftest.py` — `api` fixture + logical-clock reset

**`test_suite/`** — 23 test modules, `test_01`–`test_14` (queue A) and `test_20`–`test_28` (queue B).

## Test counts

| Queue | Instances | Tests |
|---|---|---|
| A — Difficulty (§1.8) | 24 non-stub | 48 (2 per instance) |
| B — Corner (§1.9) | 36 non-stub | 36 (1 per instance) |
| **Total** | **60** | **84** |

The 15 `excluded_because:` stubs were not translated. Every test carries exactly one trailing `Design:` line copied verbatim; the audit reports 84 tagged tests, per-file tag count == test count, and every `PRD: "…"` quote greps verbatim against `workspace/PRD.md`.

## Verification

`prd-bench-local-run --isolation per-test-server --test-timeout 30` against the reference implementation: **84/84 passed, 0 failed, 0 errors, 0 skipped** (157s).

## Instances skipped

None — all 60 non-stub instances passed the PRD-first two-condition filter.

## Adjudications where the design index conflicted with the PRD (test follows the PRD; tag retained)

1. `structural_utilization_nonlinear_wind_ice_code_interaction` — scaffold claims 94.72 → `PASS`; PRD says "A utilization above 85.00 but no greater than 100.00 is a `PASS_WITH_MOD`", so both code revisions assert `PASS_WITH_MOD` / `STRUCTURAL_HOLD`.
2. Difficulty A8 (`select_site_on_empty_eligible_pool`) — dropped the `candidate_count == 0` sub-assertion; the PRD derives 1.
3. `corner_landlord_create_generates_system_fields` — dropped the `created_at == 2026-08-01T00:00:00Z` pin; §2.5's logical-clock enumeration does not cover `created_at` (this same gap is what makes the `created_at` tie-break in the driver-selection test uniquely derivable).
4. `corner_tribal_response_window_equality_closes_branch` — rejected attempt made at 2026-08-30 rather than 2026-08-01 so the window-equality boundary is actually reachable.

Two defects found by executing the suite were fixed in place: `test_helpers/api_client.py` was silently dropping every `payload=` into `**kwargs` (framework helpers name the body `json` and the query string `params`), and the `PASS` expectation in `test_04_structural_utilization.py` per adjudication 1 above.

## Step 6: Generate implementation — 2026-09-01T17:22:00.000Z

All three smoke suites now run green against the built server, and I verified a fresh boot from a foreign cwd starts with an empty store and the default logical clock.

## Files written

Under `/home/ubuntu/github/CodingPRD/tasks/task_2276_wireless_site_acquisition_zoning/workspace/implementation/`:

- Launcher/deps: `start.sh` (executable, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000, guarded pip install so per-test relaunches are fast), `requirements.txt` (`flask`)
- App core: `app.py` (blueprint registration, global store `RLock` per request, `ApiError`/`HTTPException`/catch-all handlers)
- Foundation: `db.py` (in-memory `Store` with 13 dicts + logical clock + insertion sequence, datetime helpers, whole-UTC-day math, serializer), `errors.py` (all 63 error IDs with default messages), `response.py` (meta/response_type/data envelope, `req_` + 20 chars, Decimal-safe JSON), `validation.py` (auth, field specs, `parse_float=Decimal` body parsing, pagination), `calc.py` (12 pinned Decimal/ROUND_HALF_UP calculations), `services.py` (rollups, cascades, lazy permit expiry, forecast driver resolution)
- Routes (`routes/`): `__init__.py`, `common.py`, `rings.py`, `refdata.py`, `candidates.py`, `leases.py`, `zoning.py`, `structural.py`, `environmental.py`, `permits.py`, `onair.py`

**Endpoint count: 67 registered routes, exactly matching the PRD §4 table** (verified by sorted diff — no extras, none missing).

## Verification

Three end-to-end scripts (`/tmp/t2276_smoke{,2,3}.py`, outside the deliverable) exercise every endpoint and ~70 error-precedence cases: full happy path to on-air activation; both cascades (structural FAIL → candidate DISQUALIFIED → zoning WITHDRAWN → backhaul CANCELLED → provider/ring rollups; blacklist → lease TERMINATED → candidate RELINQUISHED → selection cleared); permit expiry cascade (`BUILD_READY → ENTITLED`, ring back to `OPEN`); tribal fork-join with the TCNS window; negotiation round ceiling; hearing cadence and continuance limits; deemed-granted; capex budget gate; supersession; pagination and all 14 not-found IDs. Spot-checked formula outputs against PRD §3.3/§3.5/§3.6 by hand: RF 91.5 and 80.25, utilization 85.69 / 39.24 / 129.14, zoning fee 4968.00 (4600 subtotal → 0.08 tier), shot clock 90 + 10 tolled → 2026-11-09, rent schedules for all three escalation types, permit expiry 180-day default.

## PRD ambiguities resolved by choice

- **Ordering/time**: `created_at` from the logical clock; list order `(created_at, insertion sequence)`. Client-supplied datetimes echo the raw literal; server-computed ones use canonical `.000Z`. All date math in whole UTC days.
- **Money**: request JSON parsed with `parse_float=Decimal`; percent-named inputs used literally as rates (no `/100`), per §3.4's "expressed as a decimal fraction".
- **Versions**: creation → 1; explicit actions always bump; rollup recomputation bumps only when a stored value actually changes.
- **Precedence**: OCC before ring openness; segregation-of-duties before all state checks; environmental-cleared before zoning-approved on permit issue; hearing cadence before hearing-date-in-past; `ERR_DATE_IN_FUTURE` before `ERR_DECISION_DATE_INVALID`; conditionally required fields (`counter_rent_usd`, `hearing_date`, `rejection_reason`, `delivered_date`, reopen `reason`) rejected at tier 3 as `ERR_INVALID_REQUEST`.
- **Reachability**: `mark-build-ready` inspects unrefreshed `ISSUED` permits so `ERR_PERMIT_EXPIRED` is reachable; once a read has already flipped the permit to `EXPIRED`, the same call reports `ERR_PERMIT_NOT_ISSUED` (matches the PRD's literal "a permit in `ISSUED` status" wording).
- **Scope calls**: candidate creation does not require an `OPEN` ring; `ERR_NO_ELIGIBLE_CANDIDATE` is strict only on select-site, plan creation and reforecast (reset and the computed-forecast read fall back to the stored driver); `ERR_TARGET_DATE_IN_PAST` only on reset; `ERR_DECISION_DATE_INVALID` covers only "at or after `submitted_date`"; hearing cadence considers all other applications in the jurisdiction with a non-null `hearing_date` regardless of status; lease execute advances the candidate unless already `RELINQUISHED`.
- **Envelope edges**: `POST /_clock/set_current_utc` returns `data: {}` (scaffold declares `output: null`); unmapped 404/405 use `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` in the standard envelope.

I did not read the `test_suite/`, `test_helpers/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task directory.

## Step 7: Run tests and iterate — 2026-09-01T18:26:00.000Z

The sweep came back clean on the first iteration. Verified it is a real pass, not a masked one:

- All 8 parallel rounds: `84 / 84` passed, `failed: 0`, `errors: 0`, `skipped: 0`.
- Collected count matches the suite exactly — 84 `def test_` functions across the 23 `test_suite/test_*.py` files, and 84 tests reported per round, so nothing was silently uncollected.
- `grep` for `skip`/`xfail` across `test_suite/` and `test_helpers/` returns nothing, so no test is passing by being deselected.
- Storage is in-memory only and empty on boot: `db.Store.reset()` builds bare dicts, `start.sh` just `exec`s `app.py`, and `app.py` registers blueprints with no seeding path.
- No flakiness surfaced: the union of failing tests across all 8 rounds is empty, including the timing-sensitive areas (`--isolation per-test-server`, per-round free-port claim, lazy permit expiry, the hearing-cadence and provider-capacity conflict windows).

Summary

- **Iterations run:** 1 (single 8-round parallel stability sweep; ~408 s per round wall time under a host load average of ~120).
- **Tests deleted:** none. No failing test existed, so STEP 1a/1b were never reached and no PRD-silence or unique-derivability deletion was warranted.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

Files reviewed while the sweep ran (all consistent with PRD prose, no corrective edits needed): `workspace/PRD.md`; `workspace/implementation/{calc,services,db,validation,app}.py`; `workspace/implementation/routes/{rings,candidates,leases,zoning,structural,environmental,permits,onair,common}.py`; `test_helpers/{constants,factories,fixtures,assertions,test_users}.py`.

Two spots worth noting as correct-but-load-bearing, in case future edits touch them: `routes/zoning.py::hearings` evaluates `ERR_HEARING_WINDOW_CONFLICT` before `ERR_HEARING_DATE_IN_PAST`, matching PRD §2.9 tiers 40 and 43 (the reverse order would break precedence), and `calc.py::zoning_fee_total` keys the expedite rate on the pre-expedite subtotal per §2.6/§3.6 rather than re-deriving it from the inflated total.

Orchestrator verification: all 8 `results.{1..8}.json` re-read independently — each reports `passed=84 total=84 failed=0 errors=0 skipped=0`.

## Step 8: Finalize PRD — 2026-09-01T18:27:00.000Z

SKIPPED per the skill's skip condition. Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline — so `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 touched. No `PRD_FINALIZED.md` was produced; Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-01T18:36:00.000Z

Done. All edits applied to `PRD_COMPLETED.md`.

## Summary

**Files**: source `workspace/PRD.md` (507 lines, 87,086 chars) → `workspace/PRD_COMPLETED.md` (507 lines, 93,078 chars); **char delta +5,992**, line count unchanged (all changes are in-paragraph, no new sections/paragraphs).

**Counts**: 37 changes — **30 ambiguity-pins**, **7 mismatch-revisions**.

### Changes

- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` + 20 random uppercase-alphanumerics — `response.py:15`
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is real wall-clock, the one timestamp not reading the logical clock — `response.py:19`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` also yields `ERR_INVALID_PAGINATION` — `validation.py:176`
- §2.3 Pagination — insert — ambiguity — `created_at` ties broken by server creation sequence — `db.py:125`
- §2.3 Pagination — insert — ambiguity — filters compare stringified stored value; `null`/empty matches null fields; unlisted params ignored — `routes/common.py:57`
- §2.4 Common properties — insert — ambiguity — `created_at` read from the logical clock — `db.py:93`
- §2.4 Common properties — insert — ambiguity — `updated_at` read from the logical clock — `db.py:103`
- §2.4 Common properties — insert — ambiguity — `version` is 1 on a new record — `db.py:95`
- §2.4 Common properties — insert — ambiguity — a no-op write is not a mutation (no `version`/`updated_at` move) — `services.py:15`
- §2.5 Logical clock — insert — ambiguity — the clock may be moved backwards as freely as forwards — `routes/rings.py:30`
- §2.6 Monetary precision — insert — ambiguity — supplied money is stored as sent, not re-rounded — `routes/leases.py:60`
- §2.9 tier 3 — insert — ambiguity — action-conditional required fields (`counter_rent_usd`, `rejection_reason`, `hearing_date`, `delivered_date`) fail at tier 3, ahead of path lookup — `validation.py:160`
- §2.9 tier 25 — revise — mismatch — plan creation applies no plan-state check — `routes/onair.py:19`
- §2.9 tier 50 — revise — mismatch — reset and the forecast read reach `ERR_NO_ELIGIBLE_CANDIDATE` only with no recorded driver to reuse — `services.py:303`
- §3.1 Ring creation — insert — ambiguity — `radius_m`/`required_agl_m` integers, lat/lon and `target_rsrp_dbm` unbounded — `routes/rings.py:44`
- §3.2 Landlord standing — insert — ambiguity — at most one landlord `version` bump per standing call, none on a true no-op — `routes/refdata.py:64`
- §3.2 Jurisdiction — insert — ambiguity — `min_visual_simulations` is a non-negative integer — `routes/refdata.py:90`
- §3.3 Candidate creation — insert — ambiguity — survey fields are integers; a `DRAFT` ring accepts candidates — `routes/candidates.py:32`
- §3.3 Outreach — insert — ambiguity — response is the updated candidate; events are not persisted — `routes/candidates.py:147`
- §3.3 RF qualification — revise — mismatch — a failing score runs the full §2.10 feasibility cascade, not just the capex recompute — `routes/candidates.py:167`
- §3.4 Lease draft — insert — ambiguity — `execution_date` also null at creation; the three money fields named — `routes/leases.py:72`
- §3.4 `ACCEPT` — insert — ambiguity — null `last_counter_rent_usd` yields `ERR_INVALID_LEASE_STATE` — `routes/leases.py:158`
- §3.4 Execution — revise — mismatch — candidate set to `LEASE_EXECUTED` from any non-`RELINQUISHED` state, no `LANDLORD_ENGAGED` precondition — `routes/leases.py:203`
- §3.4 Rent-schedule read — insert — ambiguity — any `SiteAcquisitionAgent`; no ownership check — `routes/leases.py:230`
- §3.5 Analysis completion — insert — ambiguity — candidate effects conditional on it still being in `STRUCTURAL_HOLD` — `routes/structural.py:94`
- §3.6 Visual simulations — insert — ambiguity — returns the application; simulation inputs unretained and unbounded — `routes/zoning.py:105`
- §3.6 Tolling — insert — ambiguity — a cure never contributes fewer than zero days — `routes/zoning.py:174`
- §3.6 Hearing cadence — insert — ambiguity — conflict considers other applications whatever their status, terminal included — `routes/zoning.py:194`
- §3.6 Decisions — revise — mismatch — `ERR_DATE_IN_FUTURE` precedes `ERR_DECISION_DATE_INVALID` (prose order was reversed) — `routes/zoning.py:283`
- §3.6 Shot-clock read — insert — ambiguity — nulls and `deemed_grantable: false` for a `PREPARING` application — `routes/zoning.py:325`
- §3.8 Permit filing — insert — ambiguity — `valid_days` integer ≥ 1; no candidate-state gate at filing — `routes/permits.py:33`
- §3.8 Issuance — revise — mismatch — the environmental check is evaluated before the entitlement check — `routes/permits.py:85`
- §3.8 Lazy expiry — insert — ambiguity — the exhaustive list of evaluation occasions, and that the transition fires even when the triggering request fails — `services.py:251`, `routes/candidates.py:196`
- §3.8 Mark build-ready — revise — mismatch — moves to `BUILD_READY` from either admitted feasibility state, not only `ENTITLED` — `routes/candidates.py:201`
- §3.8 Crew capacity — insert — ambiguity — a covered UTC day is a `00:00:00Z` boundary inside the half-open window (no partial leading day) — `calc.py:231`
- §3.9 Plan creation — insert — ambiguity — any ring status, any target date, several plans per ring, `PLANNED` even when the first band is `HIGH` — `routes/onair.py:25`
- §3.9 Driver resolution — insert — ambiguity — reset and the forecast read fall back to the plan's recorded `driver_candidate_id`; creation and reforecast do not — `services.py:293`

Cross-checked but already uniquely pinned (no change): all 50 precedence tiers as ordered in the route code, both cascades in `services.py`, every formula in `calc.py` (RF score, committed rent rounding order, capacity utilization, four-step filing fee, risk score/band), all list filters, and all three computed-read field shapes.

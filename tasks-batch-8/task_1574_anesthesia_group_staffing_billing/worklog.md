# Worklog — task_1574_anesthesia_group_staffing_billing

## Step 1: Create Task Directory — 2026-08-13T22:03:00.000Z

Task directory `tasks/task_1574_anesthesia_group_staffing_billing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per instructions. No other task_* directory was touched.

## Step 2: Generate Scaffold — 2026-08-13T23:42:33.482Z

RESUME NOTE: prior run was killed after writing SCAFFOLD.yaml (92,344 bytes, parses cleanly with all §1.0–§1.7 keys) but before writing the two design-index files. SCAFFOLD.yaml was kept byte-identical and reused; the resumed subagent generated only §1.8/§1.9 against it.

Step 2 complete. Both design-index files generated, linted clean, and cross-checked.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,585 lines, single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/SCAFFOLD_CORNER_DESIGN.yaml` — 3,699 lines, single top-level key `scaffold_corner_design`
- `SCAFFOLD.yaml` untouched (byte-identical; read-only input)

## §1.8 instance counts (19 total, ≥2 per rule)

| rule_id | instances |
|---|---|
| dual_variant_calc | 2 (charge money domain vs audit-score domain) |
| combinatorial_formula | **3** (one per mode: (a) charge_units multi-input tier/branch, (b) direction_split pinned nested rounding on odd gross 104013→52007/52006, (c) daily_cap_waterfall circular-dependency pinned order) |
| non_linear_state_machine | 2 (DirectionAttestation revision loop; BillingClaim denial-resubmission loop) |
| transitive_cascade | 2 (case-complete→finding→scores→band, depth≥3; credentials-PATCH→findings→scores, different trigger) |
| priority_pair_validation_conflict | 2 (business_referential vs business_fiscal; auth vs business_safety) |
| boundary_precision_check | 2 (standby notice 119/120 via cancel; rest gap 479/480 via assignment create) |
| cross_entity_state_dependency | 2 (CaseAssignment→Provider suspension; BillingClaim→DailyRoster lock) |
| resource_temporal_overlap | 2 (CallAssignment closed-interval endpoint-minute conflict vs directing capacity 4-allowed/5-rejected) |
| compensating_invariant | 2 (daily stipend cap budget across accrue+void; claim fiscal triple across denial+resubmission) |

## §1.9 instance counts (89 total: 79 live + 10 excluded_because stubs)

entities 9 · state_machines 29 · calculations 8 · validations 17 · endpoints 3 · errors 8 (all stubs) · rbac 8 · cross_cutting_layers 6 (3 live OCC + 3 layer stubs) · consistency_model 1

## Coverage and verification notes

- **scaffold_lint.py verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (63 endpoints, 13 entities, 98 live instances, 1,029 calls scanned; exit 0)
- All 57 §1.6 error codes are covered: 50 by live §1.9 instances, 7 by stubs citing the §1.8 instance that asserts them (`ERR_DUPLICATE_CLAIM`, `ERR_OWNERSHIP_MISMATCH`, `ERR_PROVIDER_SUSPENDED`, `ERR_ROSTER_NOT_LOCKED`, `ERR_CALL_WINDOW_OVERLAP`, `ERR_SUPERVISION_RATIO_EXCEEDED`, `ERR_INSUFFICIENT_REST`); `ERR_STALE_VERSION` is covered by the three live OCC instances (one per §1.2.1 rule).
- Cross-checks (custom verifier): every `grounds:` ref resolves to a declared §1.1–§1.7 element; zero unbound `${var}` placeholders; all instance names unique across both files; all `excluded_because` refs point to real §1.8 instance names; all OCC `expected_*_version` payloads are `${var}` references.
- All formula-derived assert literals were executed against §1.3 constants before pinning (104000/120000, 131250, 104013=52007+52006, 97500+12000=109500, 83200/84000, 72000, 67500, 88000, cap waterfalls 45000/5000→50000, monthly 500000/400000/100000, release tiers 12000/6000/none, risk scores 10/30/20→ELEVATED boundaries).
- Difficulty pushed past expert baseline: 3 combinatorial modes instead of the 2-instance minimum, boundary bracketing on both sides (119/120, 479/480, 1020/1021, 1439/1440, peak 4/5), deep 20+-call setup chains with clock-sweep side effects, and odd-cent rounding traps — all PRD-derivable from the existing scaffold.

Ready for Step 3 (copy INSTRUCTION.md) and Step 4 (PRD generation).

## Step 3: Copy Shared Files — 2026-08-13T23:43:05.111Z

Copied `./INSTRUCTION.md` → `tasks/task_1574_anesthesia_group_staffing_billing/workspace/INSTRUCTION.md` (1,424 bytes). No other task_* directory was touched.

## Step 4: Generate PRD — 2026-08-13T23:55:30.750Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/workspace/PRD.md`.

**Summary**

- **Line count:** 373 lines.
- **Section list:**
  - 1. Introduction (3 paragraphs)
  - 2. Global Specifications & System-Wide Principles — 2.1 RBAC (headers, 6 roles with identity prose), 2.2 API Response Structure (byte-identical verbatim block, verified by diff), 2.3 Pagination, 2.4 Logical Clock & Minute-of-Day Timekeeping, 2.5 Resource Identity/Timestamps/OCC (4 guarded writes), 2.6 Three Interval Algebras, 2.7 Credential Currency & Suspension, 2.8 Validation Pipeline & Error Precedence (priorities 1–12 with sub-orders 3b, 6a/6b/6c, 6d, 7a/7b), 2.9 Units/Money/Rounding
  - 3. Business Logic & Workflows — 9 subsections: 3.1 Roster lifecycle, 3.2 Case scheduling/rescheduling, 3.3 Assignments & safety gates (ratio/double-booking/rest), 3.4 Call coverage & early release, 3.5 TEFRA attestations, 3.6 Start/completion/cancellation cascades, 3.7 Charge units/modifiers/claims, 3.8 Stipend ledger & daily/monthly cap waterfalls, 3.9 Audits/findings/risk scoring
  - 4. Endpoint Definitions (status-code paragraph + 4-column table, all 63 endpoints)
  - 5. Error Code Catalogue (2-column table, all 57 error ids)

**Zero-Silence coverage confirmation (all three hard contracts PASS):**

- **Contract 1 (Field-Name Coverage):** every entity field (all 13 entities), every endpoint input/query/path identifier (`to_iso8601`, `expected_case_version`, `expected_roster_version`, `expected_provider_version`, `month`, `dismissal_reason`, `limit`, `offset`, …) appears verbatim in backticks — 92/92 required names present, 0 missing. Entities: 0 missing. Endpoints: 0 missing.
- **Contract 2 (Rule Coverage):** all 12 validation priorities expressed with ordering prose; all 3 `concurrency_rules` plus the case-reschedule OCC expressed (write capability + `expected_*_version` + `ERR_STALE_VERSION`/412, stale-view framing only); all 40+ state transitions with preconditions→error ids and side effects (including per-assignment version bumps, supersede cascades, PROPOSED-at-completion closes without claim); all 14 calculations in precise reconstructible prose with constants embedded (15-minute time unit, +2 emergency units, PS table P1–P6, CF rates 8000/8001/7500/4000, AD flat 3 units, ratio 4, rest 480 min, notice tiers 120/1440, daily cap 50,000¢, monthly cap 400,000¢, weights 10/30/60, band boundaries 20/50/100 with exact-boundary landings); all `applies_to` scopes enumerated; sibling branches (modifier matrix, standby/release tiers, risk bands) rendered with equal density. 0 missing.
- **Contract 3 (§3 Path Purity):** 530 backtick tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path tokens. All 57 error ids and all 64 enum/state/role values also verified present in §2/§3 prose; no fuzzy/approximating words; no operator-syntax pseudocode.

The withheld design-index files were not opened, and no sibling task directories were inspected.

## Step 5: Generate Unit Tests — 2026-08-14T00:28:35.102Z

## Files written (21 total)

**test_helpers/ (9 files):**
- `types.py` — 15 status/role/type enums + 15 entity TypedDicts (all entities carry the four common fields per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~50 methods) + module-level `api_client`
- `api_errors.py` — `ApiErrorId` (56 ids) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` shape checkers + `assert_version_incremented` (+1 relative form)
- `factories.py` — payload factories with unique-NPI sequencing + TEFRA step payloads
- `constants.py` — CF table (8000/8001/7500/4000), TIME_UNIT_MINUTES 15, REST 480, RATIO_MAX 4, caps 50000/400000, severity weights
- `test_users.py` — shared opaque-role headers + `make_physician_headers`/`make_crna_headers` entity-backed builders
- `fixtures.py` — 5 tiers: entity creators, published-roster/case-with-confirmed-primary hierarchies, `setup_completed_solo_case`, `setup_locked_roster_with_ready_claim`, `setup_directed_case` (VERIFIED attestation), `setup_credential_lapse_audit`, `setup_stipend_site`, list helpers
- `__init__.py` — barrel export (framework + PRD-specific)

**test_suite/ (12 files):** `conftest.py` + 18 `test_*.py` files (134 test functions), organized by concern: dual-variant calculations, charge engine, lifecycle loops, cascades, validation pipeline, boundaries, cross-entity gates, interval algebras, stipend ledger, roster lifecycle, case execution, entity creation, attestation/claim states, audits/findings, validations, RBAC, OCC/provider lifecycle, listing endpoints.

## Coverage verification
- **Queue A:** all 19 difficulty instances have exactly ≥2 tests each (38 tests).
- **Queue B:** all 89 non-stub corner instances have ≥1 test each (96 tests). All 10 `excluded_because` stubs verified to resolve to real difficulty instances; no placeholder tests emitted for them.
- **Design-tag audit (scripted):** 134 test functions, every docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line as its final line; zero orphan tags; zero untagged/dual-tagged functions.
- **Verbatim PRD citation audit (scripted):** 179 quoted rule-bearing segments across 134 tests, every ≥8-word segment survives literal containment against `workspace/PRD.md` (0 failures after fixing 6 RBAC docstrings that had fused PRD table rows into non-greppable form — now citing the verbatim §2.1/§3.5 prose instead).
- **No skips:** zero `pytest.mark.skip`/`skipif`/`xfail`.
- `pytest --collect-only` passes (134 collected); all files byte-compile; all `from test_helpers import ...` names resolve.

## Instances skipped
None. Every difficulty instance and every non-stub corner instance passed the PRD-first two-condition filter.

## test_helpers design decisions flagged for the Step 7 diagnostician
1. **Version assertions are relative, never absolute.** PRD §2.5 says version "starts at its initial value" without pinning that value to 1, so absolute `version == 1` claims (present in several corner instances) are non-uniquely-derivable. All tests use `assert_version_incremented(before, after)` (+1), which PRD pins verbatim ("increments by exactly one"). This preserves the instance's assertion intent (increment counting) without hard-coding an initial value.
2. **Clock dependency:** many fixtures call `POST /_clock/set_current_utc` mid-scenario; server restarts per test mean each test re-derives clock state from the 2026-08-01 startup default. All date arithmetic in tests is absolute (no reliance on prior tests).
3. **List helpers** (`list_claims`, `list_stipend_entries`, etc.) in fixtures.py use `get_success_data` and tolerate both bare-array and envelope-wrapped `data` shapes; tests that assert pagination metadata use `validate_paginated` directly.
4. **`_standby_then_late_stay` fixture** (test_09) encodes the pinned created_at ordering (standby-at-cancel precedes late-stay-at-complete) shared by both the waterfall-order and void-invariant difficulty instances.
5. **RBAC tests for role-exclusive endpoints** cite the verbatim §2.1 authorization rule plus role-description prose; the §4 endpoint table rows are referenced by section but not quoted (table markup defeats verbatim grep), keeping C1 intact while still anchoring the role restriction.

## Step 6: Generate Implementation — 2026-08-14T00:28:35.102Z

Implementation complete. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/workspace/implementation/`.

**Files written (16 total, 2,341 lines):**

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, `exec python3 app.py`, `PORT` env (default 10000), `0.0.0.0`, guarded `pip install` |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 50 | App factory, blueprint registration, ApiError/404/405/500 envelope handlers |
| `store.py` | 61 | In-memory dicts keyed by id, logical clock (default `2026-08-01T00:00:00Z`), record factory (`id`/`created_at`/`updated_at`/`version=1`), version bump |
| `errors.py` | 26 | ApiError + base constructors |
| `envelope.py` | 32 | Success/error envelope (`meta`/`response_type`/`data`, `req_` ids, 3-fractional-digit timestamps, pagination meta) |
| `validate.py` | 162 | Auth layers 1-2 (X-User-ID/X-User-Role, 6 roles), schema validation (types, enums, dates, unknown fields), pagination (limit 1-100 default 10, offset), filter application |
| `calc.py` | 241 | Decimal-based unit math (round-half-up 0.1), CF constants, pinned direction-split order, interval algebras (half-open/closed/closed-date), peak-overlap sweeps, daily cap waterfall, posture, risk scoring |
| `services.py` | 310 | Claims engine (PERSONAL/QZ/QX/QY/QK/AD), completion/cancellation cascades, clock sweeps (suspension + call auto-complete + CALL accrual), audit scan (retro-breach/credential-lapse/TEFRA-gap with dedupe), provisional charge |
| `serializers.py` | 89 | Per-entity serializers with derived posture/scores computed on read |
| `routes_core.py` | 214 | clock, sites, providers (+credentials OCC/reinstate/lapse findings), fee-schedules, stipend-agreements |
| `routes_rosters.py` | 130 | rosters CRUD + publish/unpublish/lock lifecycle gates |
| `routes_cases.py` | 418 | cases + assignments, full safety battery (credential → ratio → double-book → rest), supersede, OCC |
| `routes_calls.py` | 111 | call windows (closed-interval overlap), tiered early release |
| `routes_attest.py` | 136 | TEFRA attestations, 7-step gate (422), segregation of duties |
| `routes_billing.py` | 224 | claims lifecycle (duplicate-before-fiscal, resubmission loop), stipend entries + monthly summary waterfall + void |
| `routes_audits.py` | 118 | audit create-or-merge scan, close gate, finding resolve/dismiss |

**Coverage:** 63/63 declared endpoints registered (verified via Flask `url_map`); 57/57 declared error IDs present in code (verified by grep against the scaffold catalog).

**Smoke test:** `bash start.sh` boots cleanly and answers HTTP within ~2.5s. ~90 functional assertions passed across six probe scripts: envelope shape + pagination meta, auth/RBAC (400/403), all four OCC guards (412), roster lifecycle gates, case start/complete/cancel cascades, charge math (`16.0 units × 7500 = 120000`, odd-gross split `72009 → QY 36005 / QX 36004`, AD flat `3.0 × 4000`), provisional charge contexts, standby tiers (boundaries 120→partial, prior-day `1440+start-clock` formula), call-release tiers (full/half round-half-up/none), clock sweeps (suspension + call completion with cap-exempt CALL entries), credential reinstate, daily cap waterfall (`40000+10000` then full re-apply after void), monthly summary, rest-buffer boundary (479 rejects, 480 allows), half-open adjacency vs closed call-window endpoint conflict, 5th-room ratio rejection, retro-breach scan (1 CRITICAL + 5 MAJOR → period 210 → CRITICAL band), merge dedupe, and claim resubmission/402 fiscal gate. Fresh-boot isolation verified: after kill + re-launch via `start.sh`, `GET /rosters` returns `total_count: 0` — no seeding, no persistence anywhere.

One deliberate PRD-fidelity note: the "prior-day cancels always land in the >= 1440 tier" prose contradicts the pinned formula (`1440 + start - clock_min`); both SCAFFOLD and PRD state the formula identically, so the formula is implemented (a prior-day cancel can yield the partial tier, e.g. notice 1300 → partial).

## Step 7: Run Tests and Iterate — 2026-08-14T00:39:57.425Z

Clean 8-round parallel sweep achieved: all 8 rounds report 134/134 passed.

## Summary

**Iterations run:** 2 (initial sweep → fixes → verification sweep, 8 parallel rounds each, all rounds run to completion).

**Tests deleted:** none. Every failing assertion traced to verbatim PRD prose; all failures were test-artifact defects, not PRD-silence or unique-derivability problems.

**Diagnosis of the 7 failing tests (identical set in all 8 rounds of iteration 1 — deterministic, not flaky):**

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/test_helpers/assertions.py` — added `SiteStatus` to the `.types` import. `assert_site()` referenced `SiteStatus` (defined in types.py) without importing it → `NameError` in `test_12_entity_creation.py::TestSiteCreation::test_site_creation_defaults_and_envelope`.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/test_suite/test_04_cascades.py` — added missing `assert_version_incremented` import (used at line 157; exported from test_helpers barrel but never imported) → fixed `NameError` in `TestCredentialShortenCascade::test_patch_increments_provider_version_once_without_suspension`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/test_suite/test_15_validations.py` — added missing `create_provider` import → fixed `NameError` in `TestDuplicateGuards::test_duplicate_provider_npi_rejected`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/test_suite/test_06_boundaries.py` — added `create_fee_schedule("P100", 5)` setup step to 4 standby-tier tests (`test_notice_exactly_120_pays_partial`, `test_notice_119_pays_full`, `test_notice_exactly_1440_creates_no_entry`, `test_notice_1439_creates_partial_entry`). The tests created a case on a stipend-site roster without registering the procedure's fee-schedule row; the implementation correctly rejected case creation with `ERR_UNKNOWN_PROCEDURE_CODE` per PRD §3.2 ("it must match an existing fee-schedule row's `procedure_code`, and an unknown code is rejected with `ERR_UNKNOWN_PROCEDURE_CODE`"). Per the cardinal rule, the PRD-required check was left intact and the test setup was fixed to satisfy the PRD precondition — matching the established pattern used by the sibling late-stay and stipend-ledger tests.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in every failure — all 7 failures were missing imports or missing fixture setup steps in the test artifact.

**Note on the flagged ambiguity:** the prior-day standby-notice tests (`test_notice_1439_creates_partial_entry` etc.) assert the pinned formula reading (`1440 + start - clock_min`, verbatim in PRD §3.6) over the looser "prior-day cancels always land in the top notice tier" prose. The implementation also follows the formula. Both layers agree on the formula reading, so no deletion was needed; the tests passed once their setup bug was fixed.

## Step 8: Finalize PRD — 2026-08-14T00:43:49.231Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta**: PRD.md 373 lines, PRD_FINALIZED.md 373 lines — 0% line-count delta; exactly one sentence edited in place on line 204.

**Changes (1 total)**:
- **§3.6 (Case Execution: Cancellation cascade)** — revise — deleted the trailing clause ", so prior-day cancels always land in the top notice tier" from the `cancellation_notice_minutes` sentence, keeping the pinned formula (`1440 + scheduled_start_minute − clock_minute-of-day`) verbatim — `implementation/services.py:186-218` (formula at 188-193, tier selection at 207-218), thresholds at `implementation/calc.py:20-21`.

**Pre-edit search log (mandatory, for the single edit)**:
- (a) **Subject**: prior-day cancellation-notice claim and standby-tier selection.
- (b) **Impl paths enumerated and read**: `implementation/services.py:186-218` (`cancel_case` — the only writer of `cancellation_notice_minutes` and only creator of `STANDBY` entries; tiers applied uniformly to the computed notice with no prior-day special-casing); `implementation/routes_cases.py:270-284` (cancel endpoint gates: `ERR_CASE_NOT_CANCELLABLE`, `ERR_CLOCK_DATE_MISMATCH` for clock date strictly after service date); `implementation/calc.py:20-21` (tier thresholds 120/1440); `implementation/calc.py:171-196` (daily waterfall — bucket membership only, no tier logic); `implementation/serializers.py:34` (field exposure, no logic); `implementation/routes_cases.py:181` (null init at creation). Repo-wide grep for `notice|STANDBY|standby|cancellation_notice` confirmed no other paths.
- (c) **Wording adjustment**: none beyond the deletion itself — the edit removes a claim rather than adding one, so it cannot misdescribe any enumerated path. The retained formula sentence and retained tier/boundary sentences exactly match `services.py:188-218`: under the formula a prior-day cancel's notice spans 1 to 2878 minutes, so it can land in any tier (auxiliary test evidence: `test_06_boundaries.py::test_notice_1439_creates_partial_entry` — a prior-day cancel paying partial — directly falsified the deleted clause; `test_notice_exactly_1440_creates_no_entry` exercises the 1440 boundary).

**Step-7 items producing no edit** (with rationale):
- `test_helpers/assertions.py` SiteStatus import; `test_04_cascades.py` and `test_15_validations.py` missing imports — pure test-artifact NameError fixes, no behavioral/PRD implication.
- `test_06_boundaries.py` fee-schedule setup fix — PRD §3.2 already pins the rule verbatim ("it must match an existing fee-schedule row's `procedure_code`, and an unknown code is rejected with `ERR_UNKNOWN_PROCEDURE_CODE`", also restated in §2.8 layer 4), and impl `routes_cases.py:168-170` implements it in pipeline order (existence before the LOCKED state gate). No patch needed.

## Step 9: Complete PRD — 2026-08-14T00:50:40.177Z

Step 9 complete. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1574_anesthesia_group_staffing_billing/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` (373 lines / 61,199 chars) → `PRD_COMPLETED.md` (375 lines / 63,887 chars), char-delta +2,688.

**Counts:** 12 ambiguity-pins, 0 mismatch-revisions. The implementation matched PRD prose everywhere behavior was pinned; all edits close gaps where PRD was silent.

**Changes (all inserts, all ambiguity):**

- §2.2 Success envelope — insert — ambiguity — pinned that `api_request_timestamp` and resource `created_at`/`updated_at` use wall-clock UTC, not the logical clock — impl: store.py:6-9, envelope.py:10
- §2.2 Error envelope — insert — ambiguity — pinned fallback handlers: unmatched route → `ERR_INVALID_REQUEST` 404, wrong method → 405, unexpected fault → 500 — impl: app.py:30-42
- §2.3 Pagination — insert — ambiguity — pinned `ERR_INVALID_REQUEST` for non-integer/out-of-range `limit`/`offset`, and same-millisecond ties broken by internal creation sequence — impl: validate.py:122-152
- §2.4 Logical clock — insert — ambiguity — pinned `to_iso8601` parsing: any well-formed ISO 8601 accepted, `Z`/offsets honored, naive values read as UTC — impl: validate.py:64-77
- §2.5 Resource identity — insert — ambiguity — pinned `version` starts at 1 on creation — impl: store.py:43
- §2.7 Credential patch — insert — ambiguity — pinned that patch-raised `CREDENTIAL_LAPSE` findings dedupe like scan findings (same type/case/assignment OPEN triple) — impl: services.py:309
- §3.1 Roster lifecycle — insert — ambiguity — pinned unpublish-from-LOCKED → `ERR_ROSTER_LIFECYCLE_LOCKED`, unpublish-from-DRAFT → `ERR_ROSTER_NOT_PUBLISHED`, lock-from-DRAFT → `ERR_ROSTER_NOT_PUBLISHED` — impl: routes_rosters.py:103-107, 122-123
- §3.2 Reschedule — insert — ambiguity — pinned single-field patches merge with the existing other minute before window validation, window check precedes existence/state checks, empty minute patch is a tolerated no-op that still bumps version and revalidates, and credential currency is not re-checked on reschedule — impl: routes_cases.py:210-224, 98-148
- §3.4 Early release — insert — ambiguity — pinned release accrues a `CALL`-type stipend entry (hence daily-cap-exempt) — impl: routes_calls.py:108-110
- §3.5 Attestation create/submit — insert — ambiguity — pinned non-physician `physician_id` → `ERR_INVALID_REQUEST`; all seven step flags schema-required at submit (missing → `ERR_INVALID_REQUEST`); submission persists the supplied flags onto the record — impl: routes_attest.py:47-49, 84-85, 96-97
- §3.8 Stipend summary — insert — ambiguity — pinned `provider_id`/`month` as required query params (`ERR_INVALID_REQUEST` if missing/malformed), unknown provider → `ERR_PROVIDER_NOT_FOUND` — impl: routes_billing.py:167-174
- §3.9 Audits — insert — ambiguity — pinned POST /audits returns 201 even on merge, acting on a non-OPEN finding → `ERR_AUDIT_NOT_OPEN`, and audit scores are read-time derived so finding churn never bumps the audit's `version` (only close does) — impl: routes_audits.py:40, 97-100; serializers.py:77-84; services.py:86-89

Pipeline complete: Steps 1–9 done; workspace/PRD_COMPLETED.md exists; final 8-round sweep 134/134 passed in every round.

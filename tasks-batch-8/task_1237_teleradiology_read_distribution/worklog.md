# Worklog — task_1237_teleradiology_read_distribution

## Step 1: Create Task Directory — 2026-08-12T04:40:00.000Z

Pre-assigned output folder `tasks/task_1237_teleradiology_read_distribution` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Task index 1237, label `teleradiology_read_distribution`.

## Step 2: Generate Scaffold — 2026-08-12T05:29:00.000Z

Scaffold generation complete and lint-clean. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/SCAFFOLD.yaml` (86 KB) — §1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (74 KB) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/SCAFFOLD_CORNER_DESIGN.yaml` (128 KB) — single top-level key `scaffold_corner_design`

## SCAFFOLD.yaml contents (§1.0–§1.7)

- **Complexity profile**: quota_allocation (primary) × compliance_audit (secondary); layers: selector_policy, dual_variant_calculation, optimistic_concurrency, derived_field_reconciliation; flat topology, cyclic state shape, segregation_of_duties role model, immediate consistency
- **12 entities**: ClientHospital, Radiologist, CoverageShift, RoutingPolicy, Study, Assignment, Report, DiscrepancyCase, CriticalResultNotice, CredentialGrant, BillingPeriod, Invoice
- **12 state machines** (non-linear: Study release-revert + amendment cycle, CredentialGrant suspend/renewal cycles, DiscrepancyCase fork-join, CriticalResultNotice branching, BillingPeriod reopen revert)
- **8 calculations**: tat_deadline, study_rvu, tat_breach_and_penalty, auto_assignment_selector (9-filter eligibility + ratio ranking + created_at tie-break), fatigue_utilization, report_rvu_credit (provisional 0.8× vs final penalty-adjusted), invoice_volume_pricing (MARGINAL vs FLAT_TIER tiers 901/801/701c), invoice_total_composition (pinned per-unit after-hours rounding; 4056 vs 4055 counter-example)
- **10 ordered validations** (auth → authz → existence → payload → OCC → state → safety → constraint → temporal → fiscal)
- **61 endpoints** incl. `POST /telerad/_clock/set_current_utc` (default 2026-05-01T00:00:00Z) and `POST /telerad/_seed/finalized-studies` test-driving endpoint for billing volume
- **38 error codes**, all test-referenced; **5 roles** (Radiologist/ClientHospitalUser entity-backed; PlatformAdmin/DispatchOps/QaReviewer opaque)
- **2 OCC concurrency rules**: routing-policy supersede on ClientHospital.version, invoice regenerate on BillingPeriod.version

## Design instance counts

- **Difficulty design: 18 instances** — all 9 rules × exactly 2, with differentiation honored (RVU-credit vs invoice-pricing domains; tiered mode-(a) vs rounding mode-(b); Study vs CredentialGrant machines; sign-cascade depth 4 vs release-cascade depth 3; state-vs-safety and safety-vs-fiscal priority pairs; RVU-equality vs TAT strict-> boundaries; Study→Hospital and Assignment→Grant pairs; half-open shift vs inclusive-day grant overlap; reserved-RVU vs billable-count conserved quantities)
- **Corner design: 53 entries (51 active + 2 excluded_because stubs)** across sections: entities 9, state_machines 9, calculations 8, validations 14, endpoints 2, rbac 5, cross_cutting_layers 5, consistency_model 1

## Verification

`scaffold_lint.py` verdict block, clean on final run:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints: 61 | §1.1 entities: 12 | §1.8 instances: 18 | §1.9 instances: 51 | calls scanned: 783
```

Additional self-consistency checks passed: all grounds resolve to declared §1.1–§1.7 elements, 70 instance names unique across both design files, no forbidden concurrency vocabulary, every error code test-referenced, enum closure clean, endpoint roles ⊆ RBAC matrix. Two replay bugs were caught and fixed during authoring: `completed_rvu_24h` now sums `{SIGNED, SUPERSEDED}` reports (provisional credit survives supersede), and the reopen grace is pinned as an inclusive-day comparison (`date(now) <= period_end + 7 days`).

## Step 3: Copy Shared Files — 2026-08-12T05:29:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1237_teleradiology_read_distribution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T05:38:00.000Z

All checks pass. Generation complete.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/workspace/PRD.md` (301 lines, ~6,700 words)

**Section list:**
- §1. Introduction (2 paragraphs — capacity-pool, compliance, and logical-clock framing)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (5 roles, entity-backed vs opaque identities translated)
  - 2.2 API Response Structure (emitted **byte-identical** to the canonical block — verified)
  - 2.3 Pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending)
  - 2.4 Common Resource Properties (`id`, `created_at`, `updated_at`, `version` — all 12 entities carry the full set)
  - 2.5 The Logical Clock and Time-Driven Sweeps (startup default 2026-05-01T00:00:00Z, `to_iso8601`, three sweep families, after-hours window 22:00–07:00 UTC)
  - 2.6 Precision, Units, and Rounding (RVU 1dp, credit 2dp half-up, integer cents, exact rational ratios)
  - 2.7 Optimistic Concurrency Control (all three OCC write endpoints with `expected_hospital_version` / `expected_billing_period_version` / `expected_study_version` → `ERR_STALE_VERSION` 412)
  - 2.8 Validation Order and Resource Resolution (priority ladder 1–10, all 12 NOT_FOUND ids named)
  - 2.9 Capacity Accounting and Immediate Consistency (`reserved_rvu` / `completed_rvu_24h` / `stat_active_count` / `pending_critical_count` recomputation rules)
- §3. Business Logic & Workflows (9 subsections: hospital onboarding; roster & shifts; credentialing; routing & intake; assignment & auto-selector; reading & signing; critical-result communication; discrepancy reconciliation; billing & invoicing — no HTTP paths/methods anywhere in §3)
- §4. Endpoint Definitions (62-row table, 4 columns only)
- §5. Error Code Catalogue (38 errors, 2 columns only)

**Coverage audit results:**
- **Contract 1 (Field-Name Coverage): PASS** — entities[].fields: 77 required / 77 present / 0 missing; endpoint inputs: 58/58/0; query params: 17/17/0. All role names, state values (incl. `RETIRED` after a repair edit), and enum members present as exact backticked strings.
- **Contract 2 (Rule Coverage): PASS** — validation priority ladder 1–10 expressed with intra-priority orderings (license before credential; exclusion before shift; fatigue before STAT concurrency); 2 concurrency_rules + the assignment OCC rule expressed with endpoint, occ field, error id, and 412; all state-machine transitions (hospital, radiologist, shift, policy, study, assignment, report, case, notice, grant, period, invoice) expressed with preconditions and full multi-hop side-effect cascades; all 8 calculations (tat_deadline, study_rvu constants, tat_breach_and_penalty with strict-greater-than and floor semantics, 9-gate auto_assignment_selector with ranking/tie-breaks, fatigue_utilization with strict 24h lower bound, report_rvu_credit variants with penalty table 0/0/0.25/0.5, invoice_volume_pricing tiers 901/801/701 + MARGINAL vs FLAT_TIER + 1.5× after-hours + 250c critical add-on, invoice_total_composition pinned per-unit rounding with the 4056-vs-4055 counter-example) rendered as precise prose; all 38 error ids mentioned in §2/§3; sibling branches (PRELIMINARY/FINAL/ADDENDUM sign paths, MARGINAL/FLAT_TIER variants) given equal specification density.
- **Contract 3 (§3 Path Purity): PASS** — 515 backticked tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path combos.
- No fuzzy/approximating words; §2.2 verified byte-identical to the canonical source; the withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-12T06:00:00.000Z

All done. Summary:

## Files written

**test_helpers/** (9 files, `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/test_helpers/`)
- `types.py` — 12 entity TypedDicts (all carry full common fields per PRD §2.4) + status/enum classes
- `api_client.py` — `ApiClient(GenericApiClient)` with 44 endpoint methods covering every PRD §4 row
- `api_errors.py` — 39 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + radiologist utilization invariant checker
- `factories.py` — payload factories (input fields only)
- `constants.py` — RVU_BASE, DISCREPANCY_PENALTY, tier rates/limits, TAT defaults, escalation thresholds
- `test_users.py` — TEST_USERS constants + mandatory `make_radiologist_headers` / `make_hospital_user_headers` entity-backed builders
- `fixtures.py` — composite helpers: `create_active_hospital`, `setup_routing_ready_hospital`, `setup_credentialed_radiologist`, `setup_assignment_ready`, `setup_study_in_progress`, `setup_prelim_signed_study`, `setup_final_signed_study`, `setup_billing_period`, `seed_studies`, `generate_invoice`, `setup_invoiced_period`, plus `assign_study`/`accept_assignment`/`sign_report` with fresh OCC reads and identity threading
- `__init__.py` — barrel export

**test_suite/** (10 files, `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/test_suite/`)
- `conftest.py` + 9 test files: `test_01_hospitals_and_envelope.py`, `test_02_studies_crud_and_routing.py`, `test_03_shifts_and_grants.py`, `test_04_assignment_selector.py`, `test_05_reports_and_signing.py`, `test_06_cascades_and_cycles.py`, `test_07_notices_and_discrepancies.py`, `test_08_billing_and_invoices.py`, `test_09_rbac_and_auth.py`

## Test counts
- **Queue A (Difficulty): 36 tests over 18/18 instances** (exactly 2 per instance)
- **Queue B (Corner): 60 tests over 51/51 non-stub instances** (≥1 each)
- Total: 96 tests, all collected by pytest cleanly

## Instances skipped
None. Every instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability). The 2 corner stubs (`cross_cutting_layers/cascade_coverage_stub`, `cross_cutting_layers/dual_variant_coverage_stub`) were not translated per spec; both cross-references resolve to real difficulty instances.

## Self-check results (stage 1 + stage 2)
- Syntax compile: all 19 files OK
- Completeness audit: 0 difficulty shortfalls, 0 corner shortfalls, 0 unknown tags, 0 stub leakage
- PRD verbatim-citation pass: 118 quoted rule-bearing citations checked against PRD.md with whitespace normalization — 0 failures (one initially-broken citation fixed to the verbatim "A successful route writes the matched policy's id into the study's `routing_policy_id`...")
- C4 placement audit: all 96 tests end their docstring with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the source yaml
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in comments or docstrings (only `PRD section X.Y` citations)

Notable design decisions: TAT-breach boundary tests use the logical clock to sign exactly at `due_at` (on-time) and +60s (breach=1); the pinned after-hours rounding test asserts 4056 and explicitly rejects the forbidden 4055; priority-pair tests assert the masking error id (ERR_INVALID_STATE over ERR_LICENSURE_GAP; ERR_LICENSURE_GAP over ERR_FATIGUE_CAP_EXCEEDED) per PRD §2.8's explicit ladder.

## Step 6: Generate Implementation — 2026-08-12T06:00:00.000Z

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/workspace/implementation/`):
- `start.sh` — foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op once Flask importable), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, error handlers, all 61 routes
- `db.py` — in-memory store (12 dicts keyed by id + logical clock starting exactly `2026-05-01T00:00:00Z`); starts completely empty, no seeding
- `errors.py` — full error catalog from SCAFFOLD §1.6 with exact ids and HTTP statuses
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5 roles, entity-backed identity checks (Radiologist, ClientHospitalUser)
- `util.py` — ids, ISO-8601 timestamps (3 fractional digits), payload validation, pagination, OCC, after-hours window logic
- `services.py` — calculations and state-machine cascades

**Endpoint count:** 61 of 61 — exact (method, path) parity with the SCAFFOLD endpoint table, verified by automated diff (0 missing, 0 extra; orchestrator re-verified with path-param normalization — ROUTE PARITY: PASS).

**Entity coverage:** all 12 entities (ClientHospital, Radiologist, CoverageShift, RoutingPolicy, Study, Assignment, Report, DiscrepancyCase, CriticalResultNotice, CredentialGrant, BillingPeriod, Invoice) with full state machines, side effects, and version/updated_at bumps per PRD §2.4.

**Calculation coverage:** all 7 rules — `tat_deadline`, `study_rvu`, `tat_breach_and_penalty` (strict `>` due_at, floor whole minutes), `auto_assignment_selector` (9 gates, exact-rational utilization ranking, tie-breaks, manual-assignment error mapping in priority order), `fatigue_utilization` (strict 24h lower bound, no clawback of superseded prelim credit), `report_rvu_credit` (0.8x prelim / `(1-penalty)x` final / 0 addendum, `ROUND_HALF_UP` at 2dp), `invoice_volume_pricing` + `invoice_total_composition` (MARGINAL vs FLAT_TIER, pinned per-unit after-hours rounding — the 3×1352=4056 counter-example passes), penalty credits with per-study cap, total floored at zero.

**Boot smoke test:** passed. Fresh `bash start.sh` boots to HTTP-ready in ~2s with an empty store (`total_count=0`) and the clock at the spec default; a comprehensive end-to-end script then passed all assertions: hospital lifecycle, radiologist onboarding, shift scheduling (after-hours flag), credential grants, OCC-guarded routing policy creation with hospital version bump, study intake with TAT deadline computation, duplicate-accession rejection, route, auto-assignment with selector, stale-OCC 412, accept, prelim sign (1.2 RVU credit, critical-notice spawn, pending_critical_count), notification/readback workflow, same-reader conflict on final, final sign with discrepancy penalty (1.13 credit), prelim supersede without clawback, AUTO discrepancy case, self-reconciliation 403, reconcile, addendum cycle, cancel-of-finalized 409, clock sweeps (shift completion, notice escalation), release with exclusion list, billing period close/generate/regenerate with invoice voiding, and the auth/validation/envelope error paths.

One notable design decision: clock sweeps are idempotent and run lazily on every request (not only on `set_current_utc`), so a shift whose window already contains the logical clock is ACTIVE even when no clock advance has occurred since its creation — otherwise the first assignment attempt after shift creation would spuriously fail gate 5.

## Step 7: Run Tests and Iterate — 2026-08-12T06:23:00.000Z

Two consecutive clean 8-round sweeps (16/16 rounds, 96/96 tests each). Exiting per protocol.

## Summary

- **Iterations run**: 3 sweeps total (baseline: 13-14 failures/round, union of 14 tests; fix sweep: 96/96 x 8; confirmation sweep: 96/96 x 8).

- **Tests deleted**: none. All 14 failing tests asserted rules stated verbatim in PRD; every failure traced to a test-artifact bug (13) or an implementation over-reach (1).

- **Fixes applied to `test_helpers/`**:
  - `test_helpers/assertions.py`: added `assert_instant_equals(actual, expected)` — compares ISO-8601 timestamps as instants. PRD pins timestamp *values* ("an exact instant at second precision", §3.4) but never pins the fractional-second serialization for domain timestamps (`received_at`/`due_at`), so string equality against `"....Z"` literals was not uniquely derivable (a `.000Z` rendering is equally PRD-faithful).

- **Fixes applied to `test_suite/`**:
  - `test_01_hospitals_and_envelope.py::test_hospital_version_increments_by_one_per_mutation` — advanced the logical clock before the suspend so the PRD-required `updated_at` refresh is observable; under the frozen clock the refresh re-stamps the same value (§2.5), so the old inequality assertion contradicted PRD.
  - `test_02_studies_crud_and_routing.py` (`test_study_due_at_computed_and_extra_field_ignored`, `test_study_due_at_uses_hospital_tat_override`) — string equality → `assert_instant_equals`; computation and extra-field-ignored assertions kept.
  - `test_04_assignment_selector.py` — added missing imports (`create_active_hospital`, `create_routing_policy`, `create_study_payload`, `set_clock`) causing NameError in 4 tests; in `test_selector_tie_breaks_by_created_at` advanced the clock between the two radiologist creations so PRD's `created_at` tie-break (§3.5) actually discriminates them (was flaky 4/8 rounds — both candidates had identical frozen-clock `created_at`, leaving the outcome to the impl's non-PRD `id` tiebreak).
  - `test_05_reports_and_signing.py::test_signing_exactly_at_due_at_is_on_time` — due_at string equality → `assert_instant_equals`.
  - `test_06_cascades_and_cycles.py::test_final_sign_cascade_report_study_and_prelim_hops` — expected credit `1.125` → `1.13`; PRD §3.6 requires "rounded half-up to 2 decimal places" (1.5 x 0.75 = 1.125 -> 1.13), and the implementation was already correct.
  - `test_08_billing_and_invoices.py` — `_make_combo_invoice`: advance the logical clock between seed batches so `created_at` differs per batch, making PRD §3.9's stated tie-break fully determine unit ordering (was failing in all rounds with per-round-varying splits — full key ties fell to the impl's random-UUID tiebreak); `test_penalty_capped_and_total_floored_at_zero`: gross `901` → `1352` — received_at 00:00 UTC is before 07:00, inside the after-hours window (§2.5/§3.9), so the unit bills at round_half_up(901 x 1.5) = 1352.

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/services.py::selector_check_radiologist` + `workspace/implementation/app.py::create_assignment` — added `enforce_prelim_signer_gate` parameter; the manual-assignment branch passes `False`. Gate (9) (FINAL-phase candidate must not be the prelim signer) remains an auto-selector filter per PRD §3.5, but §3.5's manual error map names no error for it while §3.6 places `ERR_SAME_READER_CONFLICT` at sign time — the impl's assignment-time rejection made the verbatim §3.6 sign rule unreachable, breaking `test_same_reader_final_sign_rejected`'s setup.

Orchestrator verification: 8 results files on disk, all passed=96 total=96 failed=0.

## Step 8: Finalize PRD — 2026-08-12T06:29:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1237_teleradiology_read_distribution/workspace/PRD_FINALIZED.md` with exactly four scoped changes.

## Line counts
- `PRD.md`: 300 lines; `PRD_FINALIZED.md`: 300 lines — 0% line-count delta (all edits are inline sentence revisions/appends; 5 lines modified in place).

## Changes
- **§2.5** — insert — appended a sentence pinning that every stored/returned timestamp (`created_at`, `updated_at`, `received_at`, `due_at`, `first_final_signed_at`, `signed_at`, `notified_at`, `readback_at`, shift `starts_at`/`ends_at`, clock-endpoint `current_utc`) renders as ISO 8601 UTC with exactly three fractional digits (e.g. `2026-05-01T00:00:00.000Z`), and that caller-supplied instants (shift windows, seed timestamps) are parsed and re-serialized in that form — `implementation/util.py:19-24` (`iso_z`), `implementation/app.py:76,112-137,364-365,685-686,1110,1135,1139,1172,1404,1426`.
- **§3.5** — revise — selector ranking now ends "…then on the radiologist's `created_at` ascending, and finally on the radiologist's `id` ascending" — `implementation/services.py:229-234` (sort key `(ratio, stat_active_count, created_at, id)`).
- **§3.9** — revise — billable ordering now "…ties broken by `created_at` ascending and then by the study's `id` ascending" — `implementation/services.py:374`.
- **§3.5** — revise (two sentences) — manual assignment no longer claims "identical filters"/"same rules": gate (9) is an auto-selector filter only; a manually named FINAL-phase candidate who signed the prelim is accepted at assignment time and rejected at sign time with `ERR_SAME_READER_CONFLICT` per §3.6 — `implementation/app.py:855-862` (`enforce_prelim_signer_gate=False`), `implementation/services.py:174-216`, sign-time enforcement at `implementation/app.py:1124-1127` (FINAL) and `1167-1170` (ADDENDUM).

Step_7_diff items that produced **no** PRD edit (pure test/fixture artifacts; PRD already correct): test_01 clock advance (§2.5 `updated_at` re-stamp under frozen clock), test_04 missing imports, test_06 1.125→1.13 (impl and PRD both round half-up), test_08 gross 901→1352 (00:00 UTC is inside the after-hours window per §2.5/§3.9).

## Per-edit pre-edit search log
1. **Timestamp serialization** — (a) subject: wire format of every timestamp field. (b) Enumerated: `util.py:19-24` (`iso_z`, sole formatter), `util.py:53-69` (`touch`/`stamp_new`), `response.py:14-21` (envelope `api_request_timestamp`, also 3-digit), `app.py` all stamping sites (grep for `iso_z|strftime|isoformat`), plus date-only fields `valid_from`/`valid_until`/`period_start`/`period_end` (`app.py:532-533,639-640,1478-1479`) which stay `YYYY-MM-DD`. (c) Wording scoped to "timestamps/instants" and listed the affected fields explicitly so date fields are excluded; avoided claiming sub-second truncation semantics (only the 3-fractional-digit rendering is pinned), and avoided touching §3.4's "second precision" value claim.
2. **Selector tie-break** — (a) subject: auto-selector candidate ranking. (b) Enumerated: `services.py:219-235` (`auto_select_radiologist`, only ranking path; sole caller `app.py:854` auto branch). (c) None — "id ascending" matches the tuple sort over UUID strings.
3. **Invoice billable ordering** — (a) subject: unit numbering order in invoice generation. (b) Enumerated: `services.py:362-374` (`compute_invoice` billable sort, only consumer of that order; line aggregation and penalty logic downstream don't reorder). (c) None.
4. **Manual-assignment gate (9) carve-out** — (a) subject: which eligibility gates manual assignment enforces and where the same-reader conflict fires. (b) Enumerated: `app.py:832-862` (`create_assignment` manual branch), `services.py:174-216` (`selector_check_radiologist` gate 9 gated on `enforce_prelim_signer_gate`), `app.py:1124-1127` and `1167-1170` (sign-time `ERR_SAME_READER_CONFLICT` for FINAL and ADDENDUM), `app.py:930-1000` (accept/release flows — no reader-conflict check, consistent with rejection deferred to sign time); grepped for any other assignment-time same-reader check (none). (c) Also revised the earlier sentence "vetted against the same rules" (§3.5 first paragraph) to "same gates, subject to the gate-(9) carve-out…" so the two §3.5 statements don't contradict each other; wording keeps the six-error manual map verbatim and points to §3.6 for the sign-time rule rather than restating it.

## Step 9: Complete PRD — 2026-08-12T06:39:00.000Z

All edits are applied and verified. Final summary:

## PRD_COMPLETED.md produced

**Source vs. output:** `PRD_FINALIZED.md` 300 lines / 50,330 chars → `PRD_COMPLETED.md` 304 lines / 53,246 chars (+4 lines, +2,916 chars). 17 edit hunks, all inline inserts/revisions; no new sections.

**Counts:** 14 ambiguity-pins, 5 mismatch-revisions (19 distinct change bullets below; some edits bundle a pin with a companion table row).

**Changes:**

- §2.2 — revise — mismatch — `api_request_timestamp` pinned as the platform's only wall-clock read; domain timestamps remain logical — implementation/response.py:14-21
- §2.2 — insert — ambiguity — unmatched route/method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500) — implementation/app.py:48-60
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` reject with `ERR_VALIDATION` — implementation/util.py:187-206
- §2.3 — insert — ambiguity — list sort ties break by `id` ascending — implementation/util.py:216-217
- §2.4 — insert — ambiguity — `version` starts at 1; `created_at` == `updated_at` at creation — implementation/util.py:64-69
- §2.5 — revise — mismatch — "never reads the wall clock" scoped to domain data (envelope timestamp excepted) — implementation/response.py:14-21
- §2.5 — insert — ambiguity — clock-set accepts any valid instant, not only later ones — implementation/db.py:49-51
- §2.7 — insert — ambiguity — missing/non-integer `expected_*_version` → `ERR_VALIDATION` (only integer mismatch → `ERR_STALE_VERSION`) — implementation/util.py:224-231
- §2.8 — revise — mismatch — swapped rungs 3/4: payload shape (incl. non-empty required strings, JSON-object bodies) is validated before identifier resolution — implementation/app.py:976-989, util.py:76-90
- §2.9 — insert — ambiguity — `pending_critical_count` counts notices in `PENDING`/`NOTIFIED`/`ESCALATED` — implementation/services.py:120-123
- §3.2 — revise — mismatch — radiologist `status` defaults to `ACTIVE` but another initial status may be supplied at creation — implementation/app.py:243
- §3.3 — insert — ambiguity — `valid_until` before `valid_from` rejects with `ERR_VALIDATION` at create and at renew — implementation/app.py:514-515, 628-629
- §3.3 — insert — ambiguity — reinstatement past `valid_until` rejects with `ERR_INVALID_STATE` — implementation/app.py:605-608
- §3.5 — insert — ambiguity — manual-assignment gates (1) non-`ACTIVE` and (3) missing subspecialty reject with `ERR_NO_ELIGIBLE_RADIOLOGIST` — implementation/services.py:188-195
- §3.6 — insert — ambiguity — signing requires the study `IN_PROGRESS` and the report's assignment still `ACTIVE` — implementation/app.py:1085-1092
- §3.6 — insert — ambiguity — pre-existing signed final rejects with `ERR_INVALID_STATE`, checked first among the FINAL gates — implementation/app.py:1121-1122
- §3.6 — revise — mismatch — final credit penalty keys off the grade recorded on the report: null grade → 0 penalty, but a draft-supplied grade applies even with no signed preliminary — implementation/app.py:1129-1133, services.py:162-166
- §3.6 — insert — ambiguity — study cancellation also clears `assigned_radiologist_id` and, unlike release, does not append to `excluded_radiologist_ids` — implementation/app.py:789-793, services.py:251-257
- §3.6/§3.8 — insert — ambiguity — auto discrepancy case requires a signed preliminary in place; manual case creation requires PRELIMINARY/FINAL report types on the same study, else `ERR_VALIDATION` — implementation/app.py:1147, 1203-1207
- §3.8 — revise — mismatch — `OPEN → NO_ACTION_CLOSED` also allowed when the case's `grade` is null — implementation/app.py:1291
- §3.9 — insert — ambiguity — `period_end` before `period_start` rejects with `ERR_VALIDATION` — implementation/app.py:1464-1465
- §3.9 — insert — ambiguity — `line_items` emitted ordered by `hour_class` (`AFTER_HOURS` before `REGULAR`) then `tier_index` — implementation/services.py:414-415
- §3.9 — insert — ambiguity — seed endpoint: defaults `CT`/`ROUTINE`/`OTHER`/false, `count` must be a non-negative integer, hospital need only exist (not be `ACTIVE`), and `critical_finding` true also creates a `SIGNED` `FINAL` report so the invoice add-on applies — implementation/app.py:89-100, 125-141
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500) rows — implementation/app.py:48-60

Notable unobservable internals deliberately left unpinned: the lazy per-request clock sweep (indistinguishable from clock-set sweeps since the clock moves only via the endpoint) and float-vs-Decimal storage of `reserved_rvu`.

## Pipeline Complete — 2026-08-12T06:39:30.000Z

All 9 steps done. Final state: 96 tests × 8 sweep rounds all passing (results.1–8.json, passed=96 total=96 failed=0 each); workspace/PRD_COMPLETED.md present; route parity 61/61 verified.

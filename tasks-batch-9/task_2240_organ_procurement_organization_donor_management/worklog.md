# Worklog — task_2240_organ_procurement_organization_donor_management

## Step 1: Create task directory — 2026-09-01T10:59:59.000Z

Created `tasks/task_2240_organ_procurement_organization_donor_management/` and `tasks/task_2240_organ_procurement_organization_donor_management/workspace/`.

## Step 2: Scaffold artifacts generated — 2026-09-01

- `SCAFFOLD.yaml` (§1.0–§1.7): 14 entities, 8 state machines, 2 OCC rules, 8 calculations, 43 ordered validations, 48 endpoints, 56 error codes, 9 roles. `difficulty_level: expert_plus`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rules / 24 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 9 sections / 86 instances (67 executable recipes, 19 `excluded_because` stubs).
- `scaffold_lint.py`: VERDICT: clean lint (1213 calls scanned).

## Step 2: Generate Scaffold (orchestrator record, subagent summary verbatim) — 2026-09-01T12:54:38.000Z

Scaffold complete for `task_2240_organ_procurement_organization_donor_management`.

Lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2240_organ_procurement_organization_donor_management/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2240_organ_procurement_organization_donor_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2240_organ_procurement_organization_donor_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1213

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2240_organ_procurement_organization_donor_management/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`
- `worklog.md` updated with a completion entry

What was generated:
- 14 entities, 48 endpoints (incl. `POST /_clock/set_current_utc`), 8 state machines (DeathReferral, EligibilityScreening, Authorization, DonorCase with parallel physiologic/allocation/posture dimensions, Organ, MatchRun, OrganOffer, RecoveryOperation), 2 OCC concurrency rules, 8 calculation rules (referral timeliness lag, behavioral risk score, viability index, cold-ischemic projection, offer promotion selector, hospital timeliness posture with dual variants, documentation completeness, case posture), 43 priority-ordered validations, 56 error codes, 9 roles with segregation-of-duties + entity-backed hospital scoping. `difficulty_level: expert_plus`.
- §1.8: 9 rules / 24 instances.
- §1.9: 9 sections / 86 instances — 67 with fully executable `setup_api_calls` chains, 19 `excluded_because` stubs (all citing existing §1.8 instances in `rule_id / name` form).

Fixes applied this session beyond the remaining §1.9 authoring: rewrote the Authorization NOK-consent precondition so it matches validation priority 66 (ERR_NOK_HIERARCHY_VIOLATION was otherwise unreachable); corrected a superseded-run assert to `bypass_reason == null` (enum closure); replaced an invalid capture (`$.data.status` on `NextOfKinContact`) with a read of the parent authorization; and normalised every first-position path parameter to `{id}` across all three files (198/9/16 substitutions) so the sub-resource form satisfies the linter's FK reverse-reachability check — that change cleared 7 `FK_REVERSE_UNREACHABLE` findings. All 56 error codes are triggered by at least one §1.8/§1.9 instance.

## Step 3: Copy Shared Files — 2026-09-01T12:54:38.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:07:00.000Z

PRD generated and audited clean.

**Output:** `workspace/PRD.md` — 439 lines.

**Structure**
- `## 1. Introduction` — 3 paragraphs (referral-clock pain point, scope, two design commitments: regulated custodian / deterministic under test)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 RBAC (9 roles), 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified), 2.3 Pagination (limit 10/1-100, offset 0), 2.4 Identity/Timestamps/Logical Clock, 2.5 Path Resolution, Foreign Keys & Terminal-State Refusal, 2.6 Minute Arithmetic, Ratios & Rounding, 2.7 Stale-View Protection (both OCC rules), 2.8 Donor Case Posture (the two-dimensional gate), 2.9 Segregation of Duties, 2.10 Rejection Precedence (explicit 43-item ordered list, priorities 10-82, each with error ID + full `applies_to` set), 2.11 Cascades & Conserved Quantities
- `## 3. Business Logic & Workflows` — 8 subsections: 3.1 Hospital Partners & Death Referral Intake, 3.2 Eligibility Screening (behavioral risk, serology, director's ruling), 3.3 Authorization (registry branch, NOK hierarchy, documentation, rescission), 3.4 Donor Case Conversion & Physiologic Management, 3.5 Organ Registration, Evaluation & Match Runs, 3.6 Offer Sequencing, Acceptance Clocks & Compensating Withdrawal, 3.7 Recovery Surgery, Cross-Clamp & Transport Dispatch, 3.8 Final Disposition & Recertification Reporting
- `## 4. Endpoint Definitions` — 48 rows, exactly 4 columns; every method+path matches the scaffold 1:1, no extras, and every row's authorized-role set matches `endpoints[].roles` exactly
- `## 5. Error Code Catalogue` — 56 rows, exactly 2 columns; all 56 IDs present with HTTP statuses matching the scaffold

Document ends at §5 with no audit footer.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 64 required, 64 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- endpoints[].path_params: 2 required, 2 present, 0 missing
Status: PASS
```
Supplementary: `errors[].id` 56/56, `roles[].name` 9/9, declared enum values 134/134 (incl. `DOCUMENT_FRAUD`, added after the first pass), state values 54/54.

```
Rule coverage check:
- validations[]: 43 of 43 expressed, all with relative ordering and full applies_to scope (2.10)
- concurrency_rules[]: 2 of 2 expressed with write endpoint, expected_<parent>_version token, parent version mismatch, ERR_STALE_VERSION and 412 (2.7)
- state_machines[]: 8 of 8, all transitions with preconditions paired to error IDs and all side effects stated
- calculations[]: 8 of 8 reconstructible in prose, incl. 3 with divergent variants and all pinned evaluation orders
- cascades: 2 of 2 narrated hop-by-hop (depth 4 decompensation, depth 5 rescission)
- common_fields:false entities (SerologyResult, NextOfKinContact, PhysiologicObservation): noted as lacking updated_at and version
- sibling-branch symmetry: registry vs NOK authorization; ACCEPT/DECLINE/WITHDRAW_ACCEPTANCE; TRANSPLANTED/DISCARDED/RESEARCH_REFERRED/TISSUE_REFERRED - equal density
Status: PASS
```

```
Path purity check (3 only):
- backtick tokens scanned: 888
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Withheld files were respected: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 6: Generate Implementation — 2026-09-01T13:52:00.000Z

Implementation complete and verified.

**Implementation:** `workspace/implementation/` — Python 3.14 + Flask 3.1, single process, in-memory dicts only (no SQLite, no JSON on disk, no `/tmp` cache, no seeding — verified: a fresh boot returns `total_count: 0` for every collection).

### Files (21 files, 3,295 lines)

| File | Lines |
| --- | --- |
| `app.py` | 68 |
| `constants.py` | 242 |
| `db.py` | 84 |
| `errors.py` | 135 |
| `middleware.py` | 29 |
| `response.py` | 90 |
| `validation.py` | 203 |
| `requirements.txt` | 1 |
| `start.sh` | 9 |
| `routes/__init__.py` | 0 |
| `routes/admin.py` | 269 |
| `routes/allocation.py` | 171 |
| `routes/authorizations.py` | 259 |
| `routes/donor_cases.py` | 225 |
| `routes/organs.py` | 351 |
| `routes/recovery.py` | 198 |
| `routes/referrals.py` | 183 |
| `routes/screenings.py` | 192 |
| `services/__init__.py` | 0 |
| `services/calculations.py` | 174 |
| `services/domain.py` | 412 |

### Endpoint coverage: 48/48

Programmatic diff of Flask's `url_map` against the 48 `method`/`path` pairs in `SCAFFOLD.yaml`: **missing = [], extra = []** (47 under `/opo` plus `POST /_clock/set_current_utc`). All 56 error ids are mapped to their declared HTTP statuses in `errors.py`.

### Boot verification

`PORT=19240 bash start.sh` from a clean directory → server up in <3 s; `GET /opo/donor-cases` returned `200` with the correct envelope (`meta.api_request_id` `req_` + 20 alnum, 3-fraction-digit `Z` timestamp, `response_type: "array"`, `limit/offset/total_count/has_more`); process killed cleanly. The launcher is exactly `set -euo pipefail` → `cd "$(dirname "$0")"` → guarded `pip install` (no-op, Flask pre-installed) → `exec python3 app.py`, so per-test relaunch is a fresh, empty store every time.

### Behavioural verification (3 smoke suites, 120 assertions, all green)

- **Suite 1 (44/44)** — referral intake + dual lag basis, risk score 12.03 → `INCREASED_RISK`/`RECORDS_ONLY`, NOK hierarchy violation, segregation of duties, documentation-deficiency persisted *with* the 422, offer promotion `[PENDING, PENDING, QUEUED]`, decline + refill, accept + `PEER_ACCEPTED` bypass + run `CLOSED` with `slots_free == primary_offer_slots`, team ledger 120→0, CIT projection, asset legs, disposition → case `RECOVERY_COMPLETE`.
- **Suite 2 (51/51)** — full 5-hop rescission cascade (referral `NOT_CONVERTED`, `converted_donor_count` decrement, organs `AUTHORIZATION_RESCINDED`, offers bypassed, operation cancelled + OR minutes released, research referral barred), same-rank objection correctly *not* rescinding, 4-hop decompensation cascade (thoracic-only viability holds, abdominal untouched, `ERR_VIABILITY_HOLD_ACTIVE`, `NON_TRANSPLANTABLE` still allowed while `RESTRICTED`), recovery-from-decompensation, donor-loss cascade + frozen-charting block, `WITHDRAW_ACCEPTANCE` restore/re-promotion, advance expiry sweep → `EXHAUSTED`/`CANDIDATES_EXHAUSTED`, supersede with null `bypass_reason`, `ERR_STALE_VERSION`, auth/scope/pagination/404 precedence.
- **Suite 3 (25/25)** — `DEATH_NOTE` referral with null `audit_lag_minutes`, info-request budget (`ERR_SCREENING_NOT_PENDING` before `ERR_INFO_REQUEST_LIMIT_REACHED`), append-only serology rows, registry Branch A (auto-filed `REGISTRY_SCREENSHOT`, arrives documentation-complete, NOK rejected as `ERR_AUTHORIZATION_NOT_CONTACTABLE`), transport CIT single-pass projection (transit 150 / prep 45 / projected 225 / margin 495) and `ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED`, team buffer conflict, windowed recertification report on both bases.

### One interpretation fixed during this pass

`services/domain.py:close_runs_for_organ` now sweeps offers on **every** run of an affected organ (only `OPEN` runs change status/`closed_reason`). This is required for rescission hop 4, which lists `ACCEPTED` in the bypass set — an `ACCEPTED` offer always sits on a run already `CLOSED`/`ACCEPTED`, so the declared `OrganOffer ACCEPTED → BYPASSED (CASE_CLOSED)` edge would otherwise be unreachable. Donor loss keeps the narrower `{QUEUED, PENDING}` set per PRD §3.4, and a pre-existing `PEER_ACCEPTED` bypass reason is not overwritten.

## Step 5: Generate Unit Tests — 2026-09-01T15:20:00.000Z

Step complete. Everything in `test_helpers/` and `test_suite/` is generated, verified, and free of leftovers from the interrupted run.

**Generated files**

`test_helpers/` (Stage 1 infrastructure, 8 modules + package init):
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/` (Stage 2, `conftest.py` + 16 modules, **138 tests**):

| Queue | File | Tests |
| --- | --- | --- |
| A (§1.8 depth) | `test_01_dual_variant_calc.py` | 9 |
| A | `test_02_combinatorial_formula.py` | 8 |
| A | `test_03_non_linear_state_machine.py` | 11 |
| A | `test_04_transitive_cascade.py` | 6 |
| A | `test_05_priority_pair_validation_conflict.py` | 9 |
| A | `test_06_boundary_precision_check.py` | 8 |
| A | `test_07_cross_entity_state_dependency.py` | 9 |
| A | `test_08_resource_temporal_overlap.py` | 6 |
| A | `test_09_compensating_invariant.py` | 6 |
| **A total** | | **72** |
| B (§1.9 breadth) | `test_10_entity_contracts.py` | 14 |
| B | `test_11_state_machines.py` | 14 |
| B | `test_12_calculations.py` | 6 |
| B | `test_13_validations.py` | 18 |
| B | `test_14_errors_and_endpoints.py` | 6 |
| B | `test_15_rbac.py` | 5 |
| B | `test_16_concurrency_and_consistency.py` | 3 |
| **B total** | | **66** |

**Coverage audit (machine-checked against both design yamls)**
- Difficulty index: 24 non-stub instances; every one carries **>=2** tagged tests (minimum observed 2, no shortfalls).
- Corner index: 67 non-stub instances; **66 covered** with >=1 tagged test.
- 19 `excluded_because:` corner stubs deliberately **not** translated (0 tests tagged to them).
- Every test has exactly one `Design:` line; **0** unknown/dual/missing tags; 0 tags resolving to a stub.
- No `skip` / `skipif` / `xfail` anywhere; no docstring or comment mentions the scaffold.
- All PRD citations verified verbatim and >=8 words against `workspace/PRD.md`: **0 failures**. Whole suite byte-compiles; 0 unused imports and 0 imports missing from `test_helpers`.

**Instances skipped (1)**
- `Corner/validations/clearing_a_screening_with_a_confirmed_positive_nat_is_rejected` — the recipe files a confirmed-positive `HIV_NAT` on a **PENDING** screening and then asserts the director's `CLEARED` decision returns `ERR_ABSOLUTE_CONTRAINDICATION` (422) with `status_mid == PENDING`. PRD §3.2 says that filing immediately moves the screening to `RULED_OUT`, so §2.10 priority 10 (`ERR_SCREENING_NOT_PENDING`) masks priority 24 and the asserted outcome is contradicted by the contract. Fails the unique-derivability condition → skipped with no placeholder, per the skip rule.

**Fix worth flagging**
`prd_bench_local_runner.testing.validate_error()` returns the **`data` sub-object**, not the full envelope, while `test_helpers.assertions.assert_error_envelope()` requires the full body. Three call sites in `test_15_rbac.py` — and three pre-existing ones in `test_14_errors_and_endpoints.py` — were restructured to hold the `requests.Response`, call `validate_error(resp, CODE, status)`, then `assert_error_envelope(resp.json())`. Without this the envelope assertions would have raised `KeyError: 'response_type'` on every error path.

**Notes**
- `test_06_boundary_precision_check.py` is the only module using `pytest.mark.parametrize`; the parametrized function still carries exactly one `Design:` tag.
- The temporary citation-verification script and all `__pycache__` artifacts were removed.
- The suite was not executed: the implementation under `workspace/` was still being produced by the parallel implementation step, so no server was available to run against.

## Step 7: Run Tests and Iterate — 2026-09-01T15:52:00.000Z

All 8 parallel rounds pass **139/139**.

**Iterations run:** 2 sweeps (8 concurrent rounds each). Baseline: 132/139 in all 8 rounds, 7 failures, perfectly deterministic — no flakiness observed at any point.

**Tests deleted:** none. All 7 failures survived STEP 1 (PRD verbatim coverage + unique derivability); each was either a test-helper/test-setup bug or an implementation bug.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — `file_serology()`: it passed `env.clock` positionally into `serology_result_payload(marker, result, resulted_at, **overrides)`, so any caller supplying an explicit `resulted_at` (a PRD §3.2 required field) raised `TypeError: got multiple values for argument 'resulted_at'`. Now `resulted_at = overrides.pop("resulted_at", env.clock)`. Fixed 3 tests in `test_05_priority_pair_validation_conflict.py`.

**Fixes applied to `test_suite/`**
- `test_01_dual_variant_calc.py` — `test_recert_basis_switch_flips_the_windowed_timeliness_verdict` and `test_windowed_denominator_counts_only_ventilated_referrals`: both left the logical clock at the instant the referrals were created, so `referred_at == window_end`. PRD §3.8 says "`window_end` is the current logical clock instant and is **exclusive**" and in-scope referrals are those "strictly before `window_end`" — the PRD-faithful implementation correctly scoped them out (`eligible_referral_count == 0`). Setup bug: the clock now advances 5 minutes before `read_performance`, satisfying the PRD precondition the test intends to exercise.
- `test_04_transitive_cascade.py` — `test_rescission_marks_the_organ_non_transplantable_and_bypasses_its_offers`: asserted the liver's run gets `closed_reason == "CASE_CLOSED"`, but that run had already been closed with `ACCEPTED` by the acceptance, and PRD §3.3 hop four only re-closes "match runs still in `OPEN`". Setup bug: the test now also registers/evaluates a `KIDNEY_LEFT` and opens a genuinely-`OPEN` run on it, so hop four's run-closing half is exercised against its stated precondition; the liver's already-closed run is now asserted only on what PRD determines for it (its `ACCEPTED` offer becomes `BYPASSED`/`CASE_CLOSED` — the `ACCEPTED` member of hop four's bypass set — plus slot conservation). No assertion was weakened; coverage of hop four increased.

**Fixes applied to `implementation/`**
- `workspace/implementation/db.py` — `base_record()`: `created_at`/`updated_at` were stamped from `wall_now()`. PRD §1 ("every timestamp is drawn from a logical clock that an administrator drives explicitly") and §2.4 ("All domain time is read from a **logical clock**, never from wall-clock time… it never falls back to wall-clock time under any circumstance"; "Every system-stamped instant reads from this clock") require the logical clock. Now `clock_now()`.
- `workspace/implementation/services/domain.py` — `touch()`: same change, `wall_now()` → `clock_now()` for `updated_at`. Envelope `meta.api_request_timestamp` was deliberately left on wall time (§2.2 envelope metadata, not domain time). List ordering was unaffected: `db.ordered()` already tie-breaks `created_at` with an insertion sequence, and latest-observation selection already tie-breaks `(recorded_at, created_at, _seq)`.

Stray `results.*.json` and `__pycache__` artifacts were removed; the implementation remains in-memory-only with no seeded data.

## Step 8: Finalize PRD — 2026-09-01T16:06:00.000Z

Done. `PRD_FINALIZED.md` written with two inline edits.

## Line/size delta
- Lines: PRD.md 438 → PRD_FINALIZED.md 438 (+0, 0.00% — both edits are inline inside existing paragraphs).
- Words: 11,407 → 11,541 (+134, +1.17%); bytes 87,220 → 88,025 (+0.92%).

## Changes
- **§2.4 (Resource Identity, Timestamps and the Logical Clock)** — *revise* — the "Every system-stamped instant reads from this clock: …" enumeration now explicitly includes every resource's `created_at` and every managed resource's `updated_at`, and a closing sentence pins the envelope's `api_request_timestamp` as the single server-generated timestamp taken from wall-clock time rather than the logical clock — `implementation/db.py:69-73` (`base_record`), `implementation/services/domain.py:27` (`touch`), `implementation/response.py:33-52` (`wall_now` → `_meta`).
- **§3.3 (rescission cascade, hop four)** — *revise* — split the run sweep from the offer sweep: only runs still in `OPEN` become `CLOSED`/`CASE_CLOSED` and get their counters reset, while the `QUEUED`/`PENDING`/`ACCEPTED` → `BYPASSED`/`CASE_CLOSED` sweep runs over **every** match run of the affected organs (which is how the `ACCEPTED` offer on an already-closed run is reached); non-`OPEN` runs keep their existing status/`closed_reason` and counters, and offers already `BYPASSED` keep their existing `bypass_reason` — `implementation/services/domain.py:249-271` (`close_runs_for_organ`), reached via `close_case_organs` (`:277-287`) from `rescission_cascade` (`:302-320`).

## Per-edit pre-edit search log

**Edit 1 — subject: sources of server-generated timestamps.**
(b) Enumerated/read: `grep -rn "wall_now|utcnow|datetime.now|clock_now|api_request_timestamp"` over the whole implementation → `db.py:44,69` (`clock_now`, `base_record`), `services/domain.py:27,190` (`touch`, promotion selector `now`), `routes/referrals.py:56` (`referred_at`), `routes/authorizations.py:148` (`contacted_at`), `routes/organs.py:189` (`generated_at`), `routes/recovery.py:158` (`cross_clamp_at`), `routes/allocation.py:76` (`responded_at`, `offered_at`/`expires_at` via selector), `routes/admin.py:97-98` (report `window_end`/`window_start`), `routes/donor_cases.py:150` (`recorded_at` future check), `response.py:33-52` (only `wall_now` site, feeding `api_request_timestamp` in `ok`/`paginated`/`error`).
(c) Adjustment: instead of writing "no timestamp is ever wall-clock", the sentence names the envelope timestamp as the sole wall-clock value and scopes it as "not domain time", so it stays consistent with §2.4's existing "never falls back to wall-clock time" claim about domain time and with the error/list envelopes as well as success ones. `updated_at` was worded "of every resource that carries one" because the three append-only records have no `updated_at`.

**Edit 2 — subject: which runs/offers a case-closure sweep touches, and what it does to run counters and pre-existing bypass reasons.**
(b) Enumerated/read: `close_runs_for_organ` (`domain.py:249-271`) and all three call chains — rescission (`close_case_organs` with bypass set `QUEUED/PENDING/ACCEPTED`, `closed_reason` `CASE_CLOSED`), donor loss (`donor_loss_cascade` → same helper with set `QUEUED/PENDING`), decompensation (`decompensation_cascade:335`, `VIABILITY_HOLD`, set `QUEUED/PENDING`, only when the organ `was_offering`); plus every other producer of run/offer states that could leave a non-`OPEN` run holding a sweepable offer: `supersede_open_runs` (`:232-246`, bypasses `QUEUED`/`PENDING` with reason null and resets slots), `promotion_selector`'s exhaustion branch (`:218-229`, empty pool so no `QUEUED` left), the `ACCEPT` branch in `routes/allocation.py:101-125` (run `CLOSED`/`ACCEPTED`, peers `PEER_ACCEPTED`, `pending_offer_count` 0 / `slots_free` = `primary_offer_slots`), the `WITHDRAW_ACCEPTANCE` branch (`:136-155`, run returns to `OPEN`, only `PEER_ACCEPTED` bypasses restored), and `reset_run_slots` (`:156-160`).
(c) Adjustments: (i) said the offer sweep covers "every match run of those organs" but confined the status/`closed_reason`/counter changes to runs that were `OPEN`, matching the helper's `reset_slots` branch; (ii) deliberately did **not** assert that the already-closed run's reason is `ACCEPTED` — wording is "keeps the status and the `closed_reason` it already held" — so `SUPERSEDED`/`EXHAUSTED`/`VIABILITY_HOLD` runs of the same organ are also correctly described; (iii) confined the widening to §3.3 and left §3.4's hop-four and donor-loss wording verbatim, since in those cascades the bypass set is `QUEUED`/`PENDING` only and no non-`OPEN` run can hold such an offer (supersede, acceptance and exhaustion all clear them), so the narrower prose remains behaviorally equivalent there; (iv) added the "already `BYPASSED` keeps its `bypass_reason`" clause to cover the pre-existing `PEER_ACCEPTED` case flagged in the Step 7 note.

No other Step 7 item produced a PRD edit: the `fixtures.py` `resulted_at` bug is a fixture defect (§3.2 already marks `resulted_at` as a supplied, non-optional field; `routes/screenings.py:86` requires it), and both `test_01` clock-advance fixes were test-setup bugs against §3.8's already-explicit half-open, exclusive `window_end` (matched by `routes/admin.py:97-104`).

## Step 9: Complete PRD — 2026-09-01T16:25:00.000Z

All 32 edits are in-place paragraph revisions; no lines added or removed, no new sections.

**Files:** source `workspace/PRD_FINALIZED.md` = 438 lines / 88,025 chars → `workspace/PRD_COMPLETED.md` = 438 lines / 95,156 chars (**+7,131 chars**, 32 paragraphs revised, 0 lines added/removed, section headings byte-identical).

**Counts:** 32 changes total — **26 ambiguity-pins**, **6 mismatch-revisions**.

### Changes

- §2.1 Identity semantics — insert — ambiguity — a clerk omitting/non-string `hospital_partner_id` fails with `ERR_HOSPITAL_SCOPE_VIOLATION`, not `ERR_INVALID_REQUEST` — `routes/referrals.py:37-43`, `middleware.py:26-29`
- §2.3 Pagination — insert — ambiguity — `limit`/`offset` and `ERR_INVALID_PAGINATION` apply to every list endpoint incl. reverse lookups — `routes/referrals.py:179`, `routes/screenings.py:131`
- §2.3 Pagination — insert — ambiguity — `created_at` ties broken by server insertion order; offer listing falls back to `created_at` then insertion order; unrecognized filter enum values match nothing rather than erroring — `db.py:79`, `services/domain.py:49`, `routes/organs.py:76`
- §2.4 Identity/Timestamps — insert — mismatch — `version` advances by exactly one **per request** per resource, not once per field group — `services/domain.py:19-37`
- §2.5 Body shape — insert — ambiguity — body must be a JSON object; unbounded strings must be non-empty; explicit null counts as absent; booleans not coerced — `validation.py:52,60,70-112`
- §2.5 Terminal refusal — insert — mismatch — `ERR_ALREADY_TERMINAL` is reachable only for a serology result on a `RULED_OUT` screening; all other paths are masked by more specific status errors — `routes/screenings.py:90` (sole raise site)
- §2.6 Ratios — insert — ambiguity — two-decimal values serialise as plain JSON numbers (`75.0`, not `75.00`) — `response.py:44`
- §2.10 item 7 — revise — mismatch — pagination-bounds scope widened from four endpoints to every list endpoint — `routes/*.py` (all `pagination()` calls)
- §3.2 Risk assessment — insert — ambiguity — `risk_factors`/`unresolved_factors` overlap → `ERR_INVALID_REQUEST` — `routes/screenings.py:52-56`
- §3.2 Info-request cycle — insert — ambiguity — `info_request_note` validated but never persisted — `routes/screenings.py:144`
- §3.2 Director's ruling — insert — ambiguity — `ruled_out_reason` supplied with a `CLEARED` decision is discarded — `routes/screenings.py:180-184`
- §3.3 Branch A — insert — ambiguity — missing `registry_document_ref` when `registry_hit` is true → `ERR_INVALID_REQUEST` — `routes/authorizations.py:49-53`
- §3.3 Branch B — insert — ambiguity — a `registry_document_ref` on branch B is stored but files no document — `routes/authorizations.py:70`
- §3.3 Documentation — insert — ambiguity — `document_types_present` ordered by first filing; omitted `witness_name` leaves the stored one; upload returns the authorization — `routes/authorizations.py:219-229`
- §3.3 Rescission hop 2/3 — insert — ambiguity — hop-two limbs are conditional on referral `CONVERTED` / a case naming the packet; hop three also refreshes `organ_count`/`organs_recovered_count` and leaves `organs_accepted_count` alone — `services/domain.py:305-320`, `99-116`
- §3.4 Observations — insert — ambiguity — the four clinical measurements accept fractional JSON numbers; `pressor_count` must be integer — `routes/donor_cases.py:142-146`
- §3.4 Projection — insert — ambiguity — latest-observation tie-break falls through to insertion order — `services/domain.py:359`
- §3.4 Decompensation cascade — revise — mismatch — trigger is any drop into `DECOMPENSATING` (from `STABILIZING` or `OPTIMIZED`), i.e. posture becoming `RESTRICTED` when it was not — `services/domain.py:395-398`
- §3.4 Decompensation hop 4 — revise — mismatch — offer sweep hits `QUEUED`/`PENDING` offers on **every** run of those organs; only closed runs get counters reset; an `ALLOCATABLE` organ has no run touched — `services/domain.py:257-271`, `328-335`
- §3.4 Recovery from decompensation — insert — ambiguity — a 40–69 snapshot returns posture to `OPEN` via `STABILIZING` but leaves `viability_hold` set — `services/domain.py:399-403`
- §3.4 Donor loss — insert — mismatch — offer sweep again spans every run; non-`OPEN` runs keep counters; `ACCEPTED` offers survive; `organs_accepted_count` untouched — `services/domain.py:341`, `249-271`
- §3.5 Evaluation — revise — mismatch — the `ALLOCATABLE` posture gate is thoracic-only; an abdominal organ is allocatable on a `RESTRICTED` case — `routes/organs.py:96-104`
- §3.5 Match-run generation — insert — ambiguity — 201 body carries the run plus `promoted_count` — `routes/organs.py:228-230`
- §3.6 Advance — insert — ambiguity — 200 body carries the run plus `promoted_count`; advance is not posture-gated — `routes/allocation.py:168-171`
- §3.6 Respond — insert — ambiguity — run status is also a precondition (`OPEN` for accept/decline, `CLOSED` for withdraw); failed withdraw organ-preconditions yield `ERR_OFFER_NOT_PENDING`; `increased_risk_ack` stored on every decision; response is the offer — `routes/allocation.py:69-99`
- §3.6 Accept — insert — ambiguity — `allocation_status` reaches `ALLOCATED` from `MATCH_RUN_OPEN` as well as `OFFERS_IN_FLIGHT` — `routes/allocation.py:122-123`
- §3.6 Decline — insert — ambiguity — missing `decline_reason` → `ERR_INVALID_REQUEST` — `routes/allocation.py:66-67`
- §3.7 Transport assets — insert — mismatch — `active_leg_count` is recomputed only on a committed dispatch, so a later disposition does not restate it — `routes/organs.py:307` (sole `refresh_asset_legs` call)
- §3.7 Booking — insert — ambiguity — `organ_types_covered` listed in the accepted organs' registration order — `routes/recovery.py:77-78,106`
- §3.7 Cross-clamp — insert — ambiguity — the no-accepted-organ refusal is `ERR_NO_ACCEPTED_ORGANS`, checked after `ERR_OPERATION_NOT_SCHEDULED` and `ERR_CASE_FROZEN` — `routes/recovery.py:147-156`
- §3.7 Dispatch — insert — ambiguity — leg `transport_mode` need not equal the asset's registered `mode` — `routes/organs.py:259,299`
- §3.7 Asset capacity — insert — ambiguity — the dispatched organ itself and organs without both leg instants are excluded from the overlap count — `routes/organs.py:283-294`
- §3.8 Report — insert — ambiguity — `window_days`/`basis` are query parameters; invalid values → `ERR_INVALID_REQUEST`; no upper bound on `window_days` — `routes/admin.py:94-95`, `validation.py:179-203`

Notable findings: the six mismatches were the `version`-per-request rule, the pagination-scope list in §2.10, the decompensation trigger band, the two cascade offer-sweep widths, the thoracic-only evaluation posture gate, and `active_leg_count` never being recomputed outside dispatch (so §3.7's "always reflects" was literally false against the implementation).

## Pipeline complete — 2026-09-01T16:25:00.000Z

All 9 steps done. `workspace/PRD_COMPLETED.md` exists on disk. Final test state: 139/139 across 8 parallel rounds.

## Final verification sweep (orchestrator) — 2026-09-01T16:40:00.000Z

Independent 8-round parallel confirming sweep after Step 9: **139/139 in all 8 rounds**. `results.{1..8}.json` retained under `workspace/implementation/` per the output spec. `__pycache__` artifacts cleaned.

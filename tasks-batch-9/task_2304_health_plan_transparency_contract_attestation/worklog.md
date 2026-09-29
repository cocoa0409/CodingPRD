# Worklog — task_2304_health_plan_transparency_contract_attestation

## Step 1: Create task directory — 2026-09-01T14:46:14.557Z

Created `tasks/task_2304_health_plan_transparency_contract_attestation/` and `workspace/` subdirectory (name pre-allocated by the invoker; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T18:05:00.000Z

All three artifacts are complete, parse cleanly, and the lint passes on the first run:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2304_health_plan_transparency_contract_attestation/`):
- `SCAFFOLD.yaml` (2090 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1827 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (3486 lines)

Scaffold surface (`health-plan-transparency-compliance`, prefix `/compliance`):
- 13 entities, flat topology; 13 state-machine blocks (parallel shape — `ServiceProviderContract` carries independent `gag_review_status` and `data_rights_status` dimensions; `PlanYear` carries `lifecycle_status` + derived `compliance_posture`).
- 9 calculations: `penalty_accrual_posting` (per-deficiency daily rates × covered-lives tier 1.0/1.5/2.0, 100M cap, inclusive day count, duplicate suppression on `(deficiency_type, onset_date)`), `penalty_exposure_projection` (dual-variant accrued-to-date vs statutory maximum), `compensation_reasonableness_score` (weighted, TOTAL_WITH_INDIRECT vs DIRECT_ONLY variants), `tool_monthly_uptime` (half-open interval merge, 2-dp half-up, strict `<` breach), `rxdc_reconciliation_totals` (rebate-cap tier keyed on gross before deduction), `plan_year_compliance_posture` (points thresholds 6/12 inclusive), `penalty_ledger_balance`, `remediation_abatement_amount` (50%), `refresh_cycle_outcome` (5-day grace to `23:59:59.999Z`).
- 45 validations in a strict priority chain (401 -> 403 role -> path 404 -> 400 -> pagination -> FK 404 -> vendor scope -> OCC 412 -> frozen 409 -> invalid transition -> posture gate -> segregation of duties -> domain gates), 73 endpoints, 57 errors, 5 roles (`PlanSponsorAdmin`, `ComplianceOfficer`, `ExternalAuditor`, `VendorContact` entity-backed to `Vendor`, `PlatformOperator`) under a segregation-of-duties model, 2 OCC concurrency rules (`expected_plan_year_version`, `expected_contract_version`), `immediate` consistency, complexity layers: cascading_side_effects, dual_variant_calculation, ops_run_checkpoint, optimistic_concurrency, rate_threshold_triggers.

Design coverage:
- §1.8: 9 rules x 23 instances (2-3 each), every one with `grounds`, a falsifiable `distinguishing_aspect`, and a `test_recipe` with structured `setup_api_calls` and literal asserts.
- §1.9: 87 instances across all nine guide sections — entities 10, state_machines 13, calculations 7, validations 34, endpoints 5, errors 3, rbac 8, cross_cutting_complexity_layers 6, consistency_model 1 — of which 69 are full recipes and 18 are `excluded_because` stubs pointing at the §1.8 instance that already covers the corner (all references resolve; no stub carries a `test_recipe`; all 110 instance names unique across both files; all `claim_type` values drawn from the claim-extraction guide).
- No forbidden concurrency vocabulary anywhere; all `expected_*_version` values are captured variables, never literals.

## Step 3: Copy shared files — 2026-09-01T18:10:52.614Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T18:27:17.789Z

All three Hard Contracts now verify clean. The earlier "missing" results were a checker bug — the naive backtick regex was mis-pairing across the triple-backtick fences in the verbatim §2.2 block, which inverted inside/outside spans. Stripping fenced blocks first resolved it. One genuine gap surfaced and was fixed: `completion_note` (optional input on the remediation-plan completion endpoint) is now stated in §3.9.

## PRD summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2304_health_plan_transparency_contract_attestation/workspace/PRD.md` — **504 lines**, ending at §5 with no audit footer.

**Section list**

- **§1. Introduction** — 3 paragraphs (pain point -> system goals -> technical constraints)
- **§2. Global Specifications & System-Wide Principles** (10 domain-derived subsections)
  - 2.1 Actors, Headers, and Role-Based Access Control
  - 2.2 API Response Structure (fixed verbatim block)
  - 2.3 Pagination and List Ordering
  - 2.4 Resource Identity, Timestamps, and Version Discipline
  - 2.5 The Logical Clock, Interval Conventions, and Deadline Comparisons
  - 2.6 Money, Points, and Rounding
  - 2.7 Stale-Version Guards on Creation
  - 2.8 Compliance Posture: Deficiency Points, Thresholds, and the Frozen Lockdown
  - 2.9 The Rejection Ladder (all 45 priorities, ordered, with error IDs, statuses, `applies_to` scopes)
  - 2.10 Flat Addressing and Reverse Reachability
- **§3. Business Logic & Workflows** (9 subsections) — plan-year/roster setup; MRF publication + monthly refresh certification; price comparison tool uptime; gag-clause contract review (CASCADE-A, 5 links); data-rights amendment negotiation; RxDC assembly and filing (CASCADE-B); broker/consultant compensation assessment (dual variant, 3 worked examples); annual attestation with segregation of duties; penalty ledger, projection, remediation, and the compliance run (CASCADE-C)
- **§4. Endpoint Definitions** — intro paragraph + 4-column table, all 73 endpoints
- **§5. Error Code Catalogue** — 2-column table, all 57 codes

**Coverage notes**

- 13 entities / 146 fields, 13 state-machine dimensions / 54 transitions, 9 calculations, 45 validations, 73 endpoints, 57 errors, 5 roles — all represented.
- Scaffold conflicts resolved in favour of self-consistency and recorded as single global rules: list ordering (`created_at` ascending everywhere, dropping the plan-years "newest first" phrasing), header naming (`X-User-Role` per contract-level requirement over the scaffold's `X-Role`), and the unfreeze/posture-ladder overlap (written as the faithful union: 0 `COMPLIANT`, 1-5 `AT_RISK`, 6-11 `DEFICIENT`, 12+ `FROZEN`).
- All symbolic formulas translated to prose with pinned evaluation order; wrong alternatives explicitly flagged (per-component rounding, gross-keyed rebate tier, sum->multiply->round->cap for projection).
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was ever opened, grepped, or referenced.

### Hard Contract reports

```
Field coverage check:
- entities[].fields: 146 required, 146 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 45 checked, 45 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 54 checked, 54 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 45 checked, 45 matchable to error_id in prose (57 distinct error atoms, 0 missing), 0 missing
- endpoints[].side_effects / applies_to: 45 checked, 45 expressed, 0 missing
- entities[].fields[] structured content: 146 checked, 146 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked, 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 973
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate unit tests — 2026-09-01T20:20:00.000Z

The suite is complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2304_health_plan_transparency_contract_attestation/`:

## Files written

**`test_helpers/`** (9 modules, 4,319 lines): `types.py` (all domain enums/state constants), `api_errors.py` (`ApiErrorId` with 57 members + HTTP-status map), `constants.py`, `test_users.py` (8 identities, role-header builders incl. `make_vendor_contact_headers` / `headers_without_user_id`), `factories.py` (payload builders), `api_client.py` (77 endpoint methods), `assertions.py`, `fixtures.py` (90 scenario builders), `__init__.py` (flat re-export surface).

**`test_suite/`** (conftest + 17 files, 7,434 lines, **137 tests**):

| file | tests | source |
|---|---|---|
| test_01 dual-variant exposure & compensation | 6 | Difficulty `dual_variant_calc` |
| test_02 pinned formula ordering | 6 | `combinatorial_formula` |
| test_03 non-linear state machines | 8 | `non_linear_state_machine` |
| test_04 transitive cascades | 6 | `transitive_cascade` |
| test_05 rejection-ladder priority | 9 | `priority_pair_validation_conflict` |
| test_06 boundary precision | 9 | `boundary_precision_check` |
| test_07 cross-entity state dependencies | 7 | `cross_entity_state_dependency` |
| test_08 temporal overlap conventions | 6 | `resource_temporal_overlap` |
| test_09 ledger conservation invariants | 9 | `compensating_invariant` |
| test_10 entity creation & derived fields | 10 | Corner `entities` |
| test_11 state-machine transitions | 10 | Corner `state_machines` |
| test_12 calculation inputs & thresholds | 5 | Corner `calculations` |
| test_13 input range/shape rejections | 13 | Corner `validations` (1/2) |
| test_14 workflow gate rejections | 12 | Corner `validations` (2/2) |
| test_15 endpoint response contracts | 5 | Corner `endpoints` |
| test_16 authorization & error envelope | 11 | Corner `rbac` + `errors` |
| test_17 concurrency & consistency | 5 | Corner `cross_cutting_complexity_layers` + `consistency_model` |

## Coverage

- **Queue A (§1.8):** 23/23 non-stub instances, every one covered by >=2 tests (66 tests).
- **Queue B (§1.9):** 69/69 non-stub instances covered by >=1 test (71 tests) — entities 10, state_machines 10, calculations 4, validations 25, endpoints 5, errors 3, rbac 8, cross_cutting 3, consistency_model 1.
- **18 queue-B stub instances** (those carrying `excluded_because`) were not translated, as required.

## Audits (all green)

- Completeness: 137 tests / 137 `Design:` tags, 1:1; no untagged, no dual-tagged, no tag pointing at an unknown or stub instance.
- PRD citation audit: **165 citations, 0 missing** — every `PRD x.y: "..."` string survives a literal grep of `workspace/PRD.md`.
- Name audit: every imported helper, `api.*` method, factory, fixture and `ApiErrorId` member resolves; no unused imports.
- `compileall` clean; `pytest --collect-only` collects all 137.
- No occurrence of "scaffold" or any scaffold section reference in generated code.

## Skipped / narrowed

- No instance was skipped outright. One partial: in `Corner/validations/expired_amendment_execution_rejected` the design's second trigger (`revise-proposal` on a `PROPOSED` amendment expecting `ERR_AMENDMENT_EXPIRED`) was **omitted** because PRD §3.5 makes revise legal only from `COUNTERED`, so §2.9 step 10 (state legality) outranks step 25 and the PRD uniquely derives `ERR_INVALID_STATE_TRANSITION` instead. The instance is still covered by the well-founded `execute` trigger.

## Step 6: Generate implementation — 2026-09-01T19:30:00.000Z

Implementation complete and verified end to end.

## Files written (24 files, 3,494 lines total)

`/home/ubuntu/github/CodingPRD/tasks/task_2304_health_plan_transparency_contract_attestation/workspace/implementation/`

Infrastructure: `errors.py` 77 (all 57 error_ids -> HTTP status), `clock.py` 130 (logical clock, default 2026-08-01T00:00:00Z, monotonic), `response.py` 64 (meta/response_type/data envelope), `db.py` 160 (13 in-memory dicts + `txn()` version-bump context manager), `calc.py` 269 (9 calculations, `Fraction` + ROUND_HALF_UP, integer cents), `guards.py` 287 (the 45-rung rejection ladder as reusable steps), `domain.py` 306 (ledger append-only helpers, points ladder, posture recompute, compliance run), `app.py` 96, `requirements.txt` 1, `start.sh` 18.

Routes (13 blueprints, `routes/`): `plan_years.py` 187, `vendors.py` 51, `contracts.py` 222, `amendments.py` 189, `disclosures.py` 119, `mrf.py` 137, `refresh_cycles.py` 128, `tools.py` 195, `rx.py` 373, `attestations.py` 218, `ledger.py` 80, `remediation.py` 160, `clock_routes.py` 26, `__init__.py` 1.

## Endpoints

**73** implemented, confirmed by iterating `app.url_map` (74 rules minus Flask's built-in `/static`). All under `/compliance`, matching the PRD's endpoint inventory exactly.

## start.sh / port binding

```bash
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"       # harness-supplied PORT wins, else 10000
...conditional `pip install -r requirements.txt` only if `import flask` fails...
exec python3 app.py                # exec => Flask holds PID 1 of the script, foreground
```
`app.py` ends with `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=False, debug=False, use_reloader=False)` — no reloader/daemon thread, so each `per-test-server` relaunch is a clean fresh process with all 13 dicts empty (nothing seeded, preloaded or hardcoded).

## Verification

Three throwaway smoke suites (in `/tmp`, not the repo) all ended with `FAILURES: 0`, covering: refresh deadline `2027-02-05T23:59:59.999Z`; closed-period boundary-day overlap rejection; merged touching outage windows -> 555 downtime min -> 98.76% uptime, breach onset `2027-04-01`; disclosure components 100.00/25.00/35.00 -> 160.00 UNREASONABLE; RxDC gross 7,000,000 / cap 0.25 / credit 1,500,000 / net 5,500,000; both OCC rules (412); all three segregation-of-duties refusals; MRF publish -> supersede (`superseded_at` set only when the replacement publishes) and reject -> revise; CASCADE-A (gag escalation -> DEFICIENT, GAG_CLAUSE accrual 15000x1x1.5 = 22,500); CASCADE-B (validated-package rejection unwinds RECONCILED->ASSEMBLING, nulls all totals, decrements assembled count, posts RXDC_LATE with onset deadline+1 -> 20000x29x1.5 = 870,000 exposure); remediation abatement (50%) and ledger reversal with `ERR_ENTRY_ALREADY_REVERSED` / `ERR_NOT_REVERSIBLE_ENTRY`; compliance run sweeping a cycle to MISSED with `on_time` null; projection keys and `ERR_PROJECTION_DATE_OUT_OF_RANGE`; frozen lockdown with exactly its 5 exemptions, then unfreeze restoring the derived posture; and all pagination (limit 1-100, offset >= 0), FK-filter 404, path 404, method 405 and missing-field 400 edges.

Two PRD-vs-SCAFFOLD conflicts were resolved in the PRD's favour: header spelling `X-User-Role` (with `X-Role` accepted as a harmless fallback) and list ordering `created_at` ASC. Actions on existing resources return 200 (only creation returns 201), including `/penalty-ledger-entries/{id}/reverse`.

## Step 7: Run tests and iterate — 2026-09-02T04:15:00.000Z

Exit gate met. All eight rounds green with zero harness noise.

## Summary

**Exit condition: MET.** 8 sequential rounds, every round `passed == total` (137/137), classifier reports `harness noise: 0, genuine: 0`. Results in `/home/ubuntu/github/CodingPRD/tasks/task_2304_health_plan_transparency_contract_attestation/workspace/implementation/results.{1..8}.json`.

### Iterations run
5 sweep iterations, ~33 round executions. Two initial 8-round parallel sweeps were OOM-killed (no results). Two completed parallel sweeps (16 rounds, ~2192 test executions) produced **0 assertion failures and 0 implementation defects** — every non-pass was the harness's own `subprocess.TimeoutExpired` on `lsof -ti:<port> -sTCP:LISTEN`. The final sequential sweep produced 8 clean rounds on the first attempt each.

### Tests deleted
**0 deleted outright.** Two assertions removed under STEP 1a/1b/1c (each split, keeping the PRD-covered core):

1. `adjudicated_by_user_id` (2 assertions) — `test_suite/test_16_authorization_and_error_envelope.py`. **PRD-SILENCE (STEP 1a).** The field appears nowhere in PRD.md, and §2.1's audit-anchor enumeration is closed ("`prepared_by_user_id`...`posted_by_user_id` — but it never compares it to any entity's `id`"), excluding an adjudicator anchor. Scaffold rule: `Corner/segregation_of_duties`. The PRD-covered segregation-of-duties core was kept; the orphaned `AUDITOR_USER_ID` import was removed.
2. `expected_status=201` on `POST /compliance/penalty-ledger-entries/{id}/reverse` — `test_09_ledger_conservation_invariants.py` and `test_15_endpoint_response_contracts.py`. **NON-UNIQUE DERIVABILITY (STEP 1b).** PRD §4 enumerates 200 for "all state-transition and mutation actions on existing resources", yet reverse also persists a new ledger entry, so 201 is equally articulable. Every substantive field assertion was retained.

### Fixes applied to `test_helpers/`
**None.** `fixtures.py::reversed_accrual` already used the lenient any-2xx `get_success_data`, so no fixture issued a PRD-inconsistent request.

### Fixes applied to `implementation/`
No behavioral change; no PRD-visible behavior altered. Storage remains 13 in-memory dicts keyed by id (`db.py:13-25`), nothing seeded, no on-disk persistence.
- `app.py` (module-level import bootstrap) — moved the Flask dependency bootstrap in-process.
- `start.sh` — removed a `python3 -c "import flask"` probe subprocess that cost ~5s on each of the 137 boots per round.

Together these roughly halved server boot time, which cut round duration and reduced the harness's exposure window.

### Key finding: the failure signal was entirely environmental
The host runs 60+ other pipelines (load 170-380 on 32 cores, ~3400-4600 processes, active OOM killer). `pytest_plugin.py:52` calls `lsof -ti:<port> -sTCP:LISTEN` with a **hardcoded `timeout=5`** before every test, and under `per-test-server` isolation the previous server is always still listening, so the expensive path runs on all 137 calls. I confirmed the noisy test sets differ between attempts (only 3 of 14 overlapped) — uniform random ~10%, not test-specific.

I profiled the drop-in the orchestrator supplied and found the bottleneck was **not** the fd scan (0.15-0.26s) but reading `/proc/net/tcp`, which held 22,000 socket lines from other pipelines (1.1-2.5s). I wrote `/home/ubuntu/.cache/prd-bench-fastbin3/lsof`, which pushes the state+port filter into netlink via `ss -ltneH "sport = :<port>"` (one line instead of 22k) and resolves inode->pid relative-first via `/proc/<pid>/task/*/children`, since the listener is always a child of the pytest process. Measured mean 1.53s / max 2.08s versus fastbin1's 3.21/4.70 and real lsof's 3.43/6.85. Verified byte-identical output to real `lsof` on four cases (unrelated listener via fallback, child listener via fast path, `0.0.0.0` bind, empty port), with delegation intact for any other argument shape. Noise went 60-71 -> 14 -> **0**.

Two constraints I deliberately respected: I did **not** edit the shared harness, and I rejected the one artifact-side trick that would have dodged the timeout (an idle self-shutdown in `app.py` so the port would already be free) because it adds a capability with no verbatim PRD basis and could kill a server mid-test. The drop-in lives outside the artifact and is only PATH-prepended by the sweep driver `/tmp/t2304_seq5.sh` — never installed globally.

## Step 8: Finalize PRD — 2026-09-02T04:22:00.000Z

Done. Two edits, both traced to `<step_7_diff>` items.

**Line counts:** PRD.md 504 lines -> PRD_FINALIZED.md 504 lines (0% line delta; two paragraphs extended in place, +2 sentences / ~600 chars).

**Changes**
- §3.8 (adjudication paragraph) — insert — pinned that neither acceptance nor rejection writes the auditor's `X-User-ID` onto the attestation; the record has no adjudicator anchor field, leaving `prepared_by_user_id`/`submitted_by_user_id` as its only user-identity fields — `implementation/routes/attestations.py:153-190` (accept sets only `status`; reject sets `status` + `rejection_reason`), record shape fixed at `attestations.py:37-50`.
- §4 (preamble, status-code rule) — insert — pinned that an action on an existing resource stays HTTP 200 even when it appends new rows, naming ledger reversal (200, body = the newly appended reversal entry, not the untouched original) and the compliance run — `implementation/routes/ledger.py:63-80`, `implementation/response.py:31-41`.

**Pre-edit search log**

Edit 1
- (a) Subject: attestation record's user-identity/audit-anchor fields and what adjudication writes.
- (b) Enumerated & read: `routes/attestations.py` create (43-50: `prepared_by_user_id`, `submitted_by_user_id=None`), submit (129-133), `_adjudication_guards` (139-150), accept (153-166), reject (169-190, incl. `domain.post_accrual(..., user_id)`), revise (208-215, replaces `prepared_by_user_id`); `domain.py` `void_draft_attestations`/`refresh_attestation_status` (98-117, 171-179); `response.public` (`response.py:24-28`, only strips `_`-prefixed keys, so no field is hidden/added at serialization); repo-wide grep for `adjudicat*` — zero hits for any adjudicator field in `implementation/`.
- (c) Adjustment: scoped the claim to "onto the attestation itself" rather than "not recorded anywhere", because reject *does* propagate the auditor's id into the new ledger entry's `posted_by_user_id`; also phrased as "through both outcomes" so it does not contradict revise replacing `prepared_by_user_id`.

Edit 2
- (a) Subject: HTTP status + response body for POST actions on existing resources, especially ones with creation side effects.
- (b) Enumerated: grepped every `created_response`/`object_response` callsite across all 13 route modules and every `methods=["POST"]` route. All twelve 201s are top-level collection creates; every `/{id}/<action>` POST returns 200, including `ledger.py:80` (reverse), `plan_years.py:170` (compliance run, appends accruals via `domain.compliance_run`, `domain.py:241-290`), `attestations.py:190` (reject, appends an accrual), `remediation.py:160` (complete, appends an abatement), `tools.py:195` (`/evaluations`). Read `response.py` to confirm 200/201 are the only success codes.
- (c) Adjustment: avoided any "only collection-path POSTs return 201" universal (nested paths `/compliance-runs` and `/evaluations` would have made it misleading); used the generic "even when it appends new rows as a side effect" so reject/complete/evaluations are all covered, and named reverse's body explicitly since the pre-existing "return the updated primary resource" default would otherwise imply the original entry.

No PRD edit for the `app.py` / `start.sh` items (boot-time only, no PRD-visible behavior) or for `test_helpers/` (no fixture fixes were applied).

## Step 9: Complete PRD — 2026-09-02T04:34:00.000Z

Done. Summary:

**Files** — source `PRD_FINALIZED.md`: 504 lines / 112,977 chars -> `PRD_COMPLETED.md`: 504 lines / 119,403 chars (**+6,426 chars, 0 net lines**). All 28 changes are in-paragraph edits; no new sections, no new paragraphs. (No `test_helpers/` or `test_suite/` exist in this workspace, so implementation was the sole reference.)

**Counts** — ambiguity-pins: **22**; mismatch-revisions: **6**.

- §2.2 Response Structure — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not a wall clock — `response.py:20`
- §2.3 Pagination and List Ordering — insert — ambiguity — `created_at` ties break by server-side insertion sequence — `db.py:59-61`
- §2.8 Compliance Posture — insert — ambiguity — draft-voiding fires only when a recompute *changes* posture into DEFICIENT/FROZEN — `domain.py:178-179`
- §2.8 Frozen lockdown list — insert — ambiguity — contract creation added to the locked-down mutations — `routes/contracts.py:34`
- §2.9 step 4 Body schema — insert — ambiguity — required strings must be non-empty, booleans are not integers, and the six unnamed numeric floors (`covered_lives`, `annual_fee_cents`, `covered_items_count`, `expected_record_count`, `contract_terms_doc_count`, `milestone_count`) all yield `ERR_INVALID_REQUEST` at this rung, ahead of referential integrity — `guards.py:105-111`, `routes/plan_years.py:33`, `routes/contracts.py:27`, `routes/tools.py:27`, `routes/rx.py:161`, `routes/attestations.py:27`, `routes/remediation.py:38`
- §2.9 step 33 Package totals — revise — mismatch — validation re-checks only the stored `record_count`, not the monetary totals — `routes/rx.py:309-313`
- §2.9 step 39 MRF inputs — revise — mismatch — each operation checks only the inputs it carries (staging: month + row_count; validation: error_count; revision: row_count) — `routes/mrf.py:29,87,129`
- §2.10 Filters — insert — ambiguity — only the named FK filters 404; every other filter is unvalidated and simply matches nothing — `guards.py:196-208`
- §3.2 MRF staging — insert — ambiguity — `public_url`/`schema_version` stored verbatim, no scheme or schema validation — `routes/mrf.py:23,25`
- §3.2 MRF revision — revise — mismatch — revision re-checks row_count only; `posting_month` is not re-examined — `routes/mrf.py:129-131`
- §3.3 Tool registration — insert — ambiguity — `sla_target_uptime_pct` accepted as any JSON number, not range-checked — `routes/tools.py:24-26,39`
- §3.3 Outage append — insert — ambiguity — tool `status` is not a precondition; a `PENDING_LAUNCH` tool fails with `ERR_OUTAGE_WINDOW_OUT_OF_RANGE` — `routes/tools.py:132-138`
- §3.3 Evaluation — insert — ambiguity — only a `LIVE` tool may be evaluated, else `ERR_INVALID_STATE_TRANSITION` — `routes/tools.py:156`
- §3.3 Uptime computation — insert — ambiguity — merged lengths summed in seconds, then converted to minutes and rounded half up once — `calc.py:195-196`
- §3.3 Breach consequences — insert — ambiguity — a repeat breaching evaluation leaves `breach_onset_date` alone and posts no second accrual — `routes/tools.py:169-181`
- §3.4 Request remediation — insert — ambiguity — zero prohibited clauses yields `ERR_INVALID_STATE_TRANSITION` — `routes/contracts.py:123-127`
- §3.5 Amendment execution — insert — ambiguity — `DATA_RIGHTS` writes `SECURED` from any current value (never refused for state) and `GAG_CLAUSE_REMOVAL` skips the version bump when the count was already 0 — `routes/amendments.py:182-188`
- §3.6 Package registration — insert — ambiguity — no precondition on the parent submission's `status` — `routes/rx.py:166-178`
- §3.6 Package validation — revise — mismatch — re-checks the stored `record_count` only — `routes/rx.py:309-313`
- §3.8 Attestation supersede — insert — ambiguity — the `attestation_status` mirror refresh bumps the plan year's `version` on the first create but not on a superseding create — `routes/attestations.py:58-59`, `db.py:79-96`
- §3.9 Reversal — insert — ambiguity — points/posture untouched and the plan year's `version` is *not* incremented by the exposure movement — `routes/ledger.py:63-78`, `domain.py:59`
- §3.9 Remediation completion — insert — ambiguity — `completion_note` is not stored on the plan; it becomes the abatement entry's `reason` (server-generated sentence when omitted) — `routes/remediation.py:139-155`
- §3.9 Remediation completion — insert — ambiguity — the exposure recompute does not bump the plan year's `version` — `routes/remediation.py:143-159`
- §3.9 Projection — insert — ambiguity — the range check applies only to a supplied `as_of_date`; the defaulted clock date is never refused, and a malformed date is `ERR_INVALID_REQUEST` — `routes/plan_years.py:177-186`
- §3.9 Freeze — insert — ambiguity — a second freeze answers `ERR_PLAN_YEAR_FROZEN`, not a state error — `routes/plan_years.py:139-140`
- §3.9 Unfreeze — insert — ambiguity — unfreezing an unfrozen year is `ERR_INVALID_STATE_TRANSITION`; `note` is validated but stored nowhere — `routes/plan_years.py:153-155`
- §3.9 Compliance run, cycle sweep — revise — mismatch — MRF_REFRESH accrual suppression is keyed on the accrual `onset_date`, not the cycle's `period_month` — `domain.py:259-267`, `domain.py:32-36`
- §3.9 Compliance run, recompute — revise — mismatch — voiding requires an actual posture change; the run's plan-year writes collapse into one `version` increment, or none on an idempotent repeat — `domain.py:292-295`, `db.py:79-96`
- §3.9 Compliance run, response — insert — ambiguity — `run_id` is a freshly minted bare UUID, not persisted — `domain.py:298`

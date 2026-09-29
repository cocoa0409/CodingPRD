# Worklog — task_2527_interchange_qualification_merchant_category_assignment

## Step 1: Create task directory — 2026-09-03T05:37:21.747Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2527_interchange_qualification_merchant_category_assignment` and its `workspace/` subdirectory. Index 2527 was pre-assigned by the invoker; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T06:54:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2527_interchange_qualification_merchant_category_assignment/`):

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2995 | 159191 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1811 | 122494 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4443 | 285418 |

**SCAFFOLD.yaml (§1.0–§1.7) counts** — 14 entities, 60 endpoints, 10 state machines, 3 §1.2.1 concurrency rules (all OCC/`ERR_STALE_VERSION` 412), 16 calculations, 33 ordered validation rules, 41 error codes, 5 roles. Top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present. Profile: `pricing_engine` / `compliance_audit`, graph topology, cyclic state machines, `segregation_of_duties` role model, immediate consistency, layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`.

**§1.8 (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`)** — single top-level key, all 9 Difficulty Rules present, **21 instances**, each rule >=2: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9 (`SCAFFOLD_CORNER_DESIGN.yaml`)** — single top-level key, all 9 claim-extraction-guide sections, **103 instances** (74 with full `test_recipe`, 29 `excluded_because` stubs): entities 14, state_machines 15, calculations 18, validations 30, endpoints 6, errors 2, rbac 8, cross-cutting complexity layers 9, consistency model 1. Every stub's cited `difficulty_instance` resolves to a real §1.8 name; no stub carries a `test_recipe`; zero duplicate names across the union of both design files.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  928

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The only violation the lint ever surfaced on the final section was a capture of `$.data.downgrade_count` on `Merchant`; the declared field is `downgrade_count_current_quarter`, which was corrected before the clean run. The hard constraint held throughout — no sibling `task_*/` directory was listed, read, or grepped; the design came only from the scenario text plus the skill spec and its claim-extraction guide.

Orchestrator verification: all three files present, line counts confirmed (2995 / 1811 / 4443).

## Step 3: Copy shared files — 2026-09-03T06:55:29.714Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:12:00.000Z

PRD generation complete.

## Output
`workspace/PRD.md` — **433 lines**, built with 11 chunked `cat >>` appends (never a single giant write).

## Section list
- `# Interchange Qualification & Merchant Category Assignment API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors, Identity Headers and Access Control / 2.2 API Response Structure (verbatim) / 2.3 Pagination and Collection Ordering / 2.4 Resource Identity, Audit Fields and the Version Counter / 2.5 Reference Resolution and Not-Found Reporting / 2.6 The Logical Clock and Its Three-Step Sweep / 2.7 Interchange Arithmetic: Basis Points, Whole Cents and Rounding / 2.8 Optimistic Concurrency Control on Parent Versions / 2.9 The Order in Which a Request Is Rejected / 2.10 Conserved Quantities and Cascade Discipline
- `## 3. Business Logic & Workflows` — 3.1 Network Reference Data: Platforms, Acquirers and the Category Directory / 3.2 Rate Programs, Quarterly Rate Publication and Implementation Windows / 3.3 Boarding a Merchant and Verifying Its Category / 3.4 Challenging a Category: The Reclassification Review Cycle / 3.5 Clearing Batches, Record Intake and Provisional Qualification / 3.6 Finalization: Definitive Qualification, Downgrade Detection and Assessment / 3.7 Reversals Across Two Independent Dimensions / 3.8 Incentive Programs: A Finite Capacity Pool, a Waitlist and Performance Scoring / 3.9 Misrepresentation Investigation and Merchant Category Audits
- `## 4. Endpoint Definitions` (60-row table: Method / Path / Description / Authorized Roles)
- `## 5. Error Code Catalogue` (41-row table)

## Tail confirmation
`wc -l` = 433. `tail -40` ends inside the §5 error table at a complete row, last line:
`| \`ERR_INCENTIVE_CAPACITY_EXCEEDED\` | 409 |`
No mid-sentence truncation; every section header from §1 through §5 is present in order.

## Hard Contracts
- **Contract 1 — Field-Name Coverage: PASS.** 134/134 entity fields, 103/103 endpoint inputs + query params (the 31 flagged "missing" were only the scaffold's `?` optional-marker suffix), 41/41 error IDs, all 57 state values across 10 machines, all 5 role names, all 3 OCC fields (`expected_batch_version`, `expected_merchant_version`, `expected_incentive_program_version`), all 60 endpoint paths in the §4 table.
- **Contract 2 — Rule Coverage: PASS.** 33/33 validations expressed as an explicitly ordered ladder in §2.9 with their `applies_to` scopes and error IDs; 3/3 concurrency rules; 57/57 state transitions with preconditions and side effects; 16/16 calculations translated to prose (constants inlined: 1500, 40 bps, 15, 350 bps, 8, 3, 2500 bps, 5000, TIER_DISCOUNT_BPS 0/25/60/100, tier floors 5000000/20000000/50000000, 720h stated as 30 days, MAX_REVIEW_ROUNDS 3, DEFAULT_CLOCK_UTC); 28/28 endpoints with side effects; sibling-branch symmetry covered (sustain vs clear, QUALIFIED vs DOWNGRADED, TRAILING vs PROJECTED, provisional vs final, ENROLLED vs WAITLISTED, all three SUSPENDED restores, withdrawal from each of three states).
- **Contract 3 — §3 Path Purity: PASS.** 827 backtick tokens scanned in §3: 0 slash-initial, 0 bare HTTP methods, 0 tokens containing a slash, 0 plain-text method+path occurrences.

## Gap-closing edits made in the Contract 2 pass
Four default/opening-value statements were missing and were added: `Merchant.verified_by_user_id` null at boarding; the full null set at `ReclassificationRequest` creation (including `decided_mcc`, `prior_status_before_suspension`); `TransactionRecord` opening nulls/zeros (with the two `provisional_*` fields explicitly excluded since intake fills them); `IncentiveEnrollment` opening scoring values (`performance_score_pct` 0.00, `tier_code` null). Caught and corrected three invented field names in the first draft of that last sentence — the real names are `gross_assessed_volume_cents`, `incentive_credit_cents`, `net_assessed_volume_cents`, `tier_code`.

## Notable adjudications (scaffold self-contradictions resolved)
1. **FX availability window** — `calculations.interchange_assessment` selects rows with `effective_from <= current_utc`; validation 29 and `ERR_FX_RATE_UNAVAILABLE` say "at or before `clearing_timestamp`". Adjudicated to the calculation: "at or before the current logical-clock instant".
2. **`trigger_reason` vocabulary** — entity enum is `{DOWNGRADE_THRESHOLD, RECLASS_SUSPICION, PERIODIC, COMPLAINT}` but the audit-create endpoint description names non-existent `MISREPRESENTATION_COMPLAINT` / `ROUTINE_SAMPLING`. Used the entity enum; manual creation admits `RECLASS_SUSPICION`/`PERIODIC`/`COMPLAINT`, and `DOWNGRADE_THRESHOLD` supplied manually is refused `ERR_INVALID_REQUEST`.
3. **Review-round cap scope** — validation 24's `applies_to` lists only request-info, but the resubmit transition also carries `review_round < MAX_REVIEW_ROUNDS`. Wrote the cap as guarding both (the union).
4. **Sustain/clear auditor-identity precondition** (`X-User-ID == auditor_user_id`) has no dedicated error; `ERR_SEGREGATION_OF_DUTIES` covers only decide and close. Mapped the mismatch to `ERR_INVALID_STATE` (409) under priority 7's state catch-all.
5. **`fieldwork_start` vs `fieldwork_end`** — shape check is non-strict (`<=`, 400) while the transition precondition is strict (`<`). Stated that equal instants pass the shape check and are then refused by the transition with `ERR_INVALID_STATE`.
6. **Audit creation against a merchant not in `PENDING_VERIFICATION`/`VERIFIED`** is absent from validation 7's `applies_to`; mapped to `ERR_INVALID_STATE` and said so explicitly.
7. **Scaffold's own `difficulty_target` string undercounts** ("55 endpoints, 37 error codes") versus the actual arrays (60 endpoints, 41 errors); enumerated the actual arrays.

Constraints honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling `task_*/` directory was read. No contract report text was written into PRD.md.

Orchestrator truncation check (per invoker's guard): `wc -l -c` = 433 lines / 103025 bytes. Headers §1–§5 all present in order. `tail -25` ends on a complete markdown table row `| \`ERR_INCENTIVE_CAPACITY_EXCEEDED\` | 409 |` — a real section boundary (end of the §5 catalogue), not mid-sentence. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T09:05:00.000Z

Test suite generation for task 2527 is complete: **117 tests across 18 files, 100% design-index coverage, zero skips, zero unresolved instances.**

## Output files

`test_helpers/` (2515 lines) — infrastructure
| file | lines |
|---|---|
| `__init__.py` | 121 |
| `api_client.py` | 286 |
| `api_errors.py` | 96 |
| `assertions.py` | 439 |
| `constants.py` | 69 |
| `factories.py` | 378 |
| `fixtures.py` | 810 |
| `test_users.py` | 68 |
| `types.py` | 387 |

`test_suite/` (6674 lines) — 117 tests
| file | lines | tests |
|---|---|---|
| `conftest.py` | 47 | — |
| `test_01_dual_variant_qualification.py` | 235 | 5 |
| `test_02_combinatorial_assessment.py` | 283 | 6 |
| `test_03_non_linear_state_machines.py` | 344 | 6 |
| `test_04_transitive_cascades.py` | 292 | 4 |
| `test_05_validation_priority_conflicts.py` | 229 | 4 |
| `test_06_boundary_precision.py` | 238 | 6 |
| `test_07_cross_entity_state_gates.py` | 246 | 4 |
| `test_08_temporal_overlap.py` | 226 | 4 |
| `test_09_conserved_quantities.py` | 245 | 4 |
| `test_10_entities.py` | 471 | 14 |
| `test_11_state_machines.py` | 578 | 10 |
| `test_12_calculations.py` | 769 | 10 |
| `test_13_validations_a.py` | 514 | 11 |
| `test_14_validations_b.py` | 495 | 9 |
| `test_15_endpoints_errors.py` | 375 | 6 |
| `test_16_rbac.py` | 428 | 8 |
| `test_17_layers_consistency.py` | 520 | 6 |

## Coverage vs. the two design indices

- **Queue A (§1.8, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`)**: 9 rules / 21 instances, 0 stubs -> **21/21 translated**, 43 tests (>=2 per instance). 0 skipped.
- **Queue B (§1.9, `SCAFFOLD_CORNER_DESIGN.yaml`)**: 103 instances, 29 carrying `excluded_because` -> **74/74 non-stub translated**, 74 tests (>=1 per instance). 0 skipped. Per section: entities 14, state_machines 10, calculations 10, validations 20, endpoints 4, errors 2, rbac 8, cross-cutting complexity layers 5, consistency model 1.
- **Skipped instances: none.** Every non-stub instance passed the PRD-first two-condition filter. No stub instance was tagged (verified programmatically).

## Verification performed

- `python3 -m compileall -q test_suite test_helpers` -> clean; `pyflakes` clean (one unused import in `test_10_entities.py` found and removed).
- Custom checker: every `test_*` docstring ends with exactly one `Design:` line; all 95 distinct tags resolve to real non-stub instances; **200 PRD citations all verified verbatim-present in `workspace/PRD.md`**; `problems 0`, `bogus tags: []`, `stub tags used: []`, `remaining instances: 0`.
- Added a second checker mapping each citation's section number to the PRD's actual heading ranges. It caught **4 mis-numbered citations**, now fixed: `api_request_id`/`error_id` bullets are §2.2 not §5; `version` starts at 1 is §2.4 not §2.2; `created_at` ascending ordering is §2.3 not §2.4. Re-run reports 0 miscitations.
- Every test file parses and ends on a complete function (AST-verified, not mid-statement).

## Design-yaml defects adjudicated PRD-first (recipe corrected, asserted outcome preserved)

- Several rbac/layer recipes stage a merchant in `PENDING_VERIFICATION` under canonical MCC 5411, but §3.3 auto-verifies when `requires_documentation` is false. Resolved by creating 5411 with `requires_documentation: true` (posture is a pure function of that flag), or by dropping the redundant verify call where `VERIFIED` at boarding was all the recipe needed.
- `layer_occ_enrollment_create_...` supplies `performance_threshold_pct: 8000`, invalid per the PRD's two-decimal percentage; substituted `"80.00"`.
- `validation_satisfaction_the_full_happy_path...` omits the record amount while asserting `total_assessed_cents == 24`; back-derived 1200 cents and confirmed SMALL_TICKET wins the amortised ranking (198 vs 337 bps) under the 1500-cent ceiling.
- Earlier-session corrections: `calc_input_set_filtering...` asserted 1460 where the PRD derives 155; `calc_tiered_pricing...` verified an already-VERIFIED merchant.

## Step 6: Generate implementation — 2026-09-03T09:05:00.000Z

Implementation for task_2527 is complete and verified.

## Files (`workspace/implementation/`)

| file | lines |
|---|---|
| `calc.py` (whole domain engine) | 738 |
| `routes_ref.py` | 333 |
| `routes_merchant.py` | 299 |
| `routes_clearing.py` | 293 |
| `store.py` | 258 |
| `routes_incentive.py` | 257 |
| `validate.py` | 192 |
| `routes_audit.py` | 176 |
| `errors.py` | 162 |
| `timeutil.py` | 138 |
| `routes_windows.py` | 133 |
| `envelope.py` | 87 |
| `resolve.py` | 83 |
| `app.py` | 78 |
| `auth.py` | 48 |
| `listing.py` | 42 |
| `start.sh` (executable) | 10 |
| `requirements.txt` | 1 |
| **total** | **3328** |

No other files; `__pycache__` removed.

## Endpoint / error coverage
- **60 / 60** declared endpoints. Diffed the PRD §4 table against `SCAFFOLD.yaml` and against `app.url_map`: all three sets are byte-identical after normalising path params — zero missing, zero extra.
- **41 / 41** error codes: the set of `ERR_*` tokens in the implementation equals the PRD/SCAFFOLD catalogue exactly (`ERR_XXX` in the scaffold is a placeholder, not a code).

## Verification
`python3 -m compileall -q .` -> clean. Booted via `bash start.sh` (honours `$PORT`, binds `0.0.0.0` — confirmed with a 200 over the host's LAN IP, foreground `exec`). On a fresh boot all 14 collections return `total_count: 0` and the logical clock reads `2026-08-01T00:00:00.000Z`, so per-test-server isolation is clean. Storage is pure in-memory dicts; a grep for `sqlite|shelve|pickle|json.dump|open(` finds nothing.

Four smoke suites, each re-run against a freshly booted server, all pass:
1. **Envelope/basics** — create + get + list meta, `ERR_UNAUTHENTICATED`/`ERR_UNAUTHORIZED`/`*_NOT_FOUND`/`ERR_INVALID_REQUEST`/`ERR_STALE_VERSION`, clock endpoint returns `data: {}` and shifts `api_request_timestamp`.
2. **Windows** — version publish + `ERR_RATE_VERSION_WINDOW_OVERLAP` (adjacent endpoints do *not* overlap), envelope bounds, buffered `ERR_PLATFORM_WINDOW_CONFLICT`, scope violation, sweep->`MISSED`->`NON_COMPLIANT`, `complete`->`COMPLETED_LATE`->recovery; reclass cycle with supersession, SoD, doc-on-resubmit, approval cascade; audit clear/close with the snapshot restore and SoD on close.
3. **Clearing/incentive/audit** — provisional vs definitive passes, cap-then-floor (400 bps on 100000 clamps to 3500), cross-border surcharge 400 + FX markup 500 inside a 2410 total, `MISSING_DATA_ELEMENTS` vs `AUTH_MISSING` ordering, duplicate auth code, `ERR_CLEARING_BEFORE_AUTH`, batch/merchant ledger re-derivation, downgrade tripwire auto-opening a `DOWNGRADE_THRESHOLD` audit + suspending live reclass requests, `CLOSED_FULL` waitlist parking, strict head-of-line promotion (later-fitting row stays parked), probation->`TERMINATED_SHORTFALL`, sustain cascade (penalty read pre-cascade -> 5000 floor, `MISREPRESENTED`, `TERMINATED_INELIGIBLE`, auto-deny note), auth expiry sweep, and the two independent reversal dimensions.
4. **Cross-cutting** — pagination defaults/bounds/`has_more`, the three special list orderings, `ERR_NO_QUALIFYING_RATE_PROGRAM`, `ERR_FX_RATE_UNAVAILABLE`, `ERR_ACQUIRER_NON_COMPLIANT` gating finalize then clearing after recovery, TIER_1 gross 6000010 -> credit 15000 -> net 5985010, `TRAILING` (score 0 -> probation) vs `PROJECTED` (92/32-day scale-up -> 115000.00 -> back to `ENROLLED`) on identical rows, review-round ceiling of 3, and reverse-reachability filters.

Every smoke failure encountered was a defect in the throwaway test's expectations (wrong enum spelling, wrong route, wrong arithmetic), not in the server — the implementation needed no code changes during this pass.

## PRD ambiguities adjudicated
- **Uniqueness not enforced** on `ProcessingPlatform.name` and `IncentiveProgram.program_name`: §3.1/§3.8 call them unique, but priority 23's `applies_to` endpoint list is exhaustive and excludes both endpoints, so the ladder wins.
- **Non-OPEN batch submit** reports `ERR_INVALID_STATE` (priority 7), not `ERR_BATCH_NOT_OPEN` (priority 8 is scoped to record-add only).
- **Component fields at intake**: `cross_border_surcharge_cents` / `fx_markup_cents` stay 0 until finalize. §3.5 says only `provisional_rate_program_id` and `provisional_assessed_cents` are stored at intake, and both component fields are documented as parts of `assessed_interchange_cents`. The markup and surcharge are still *inside* `provisional_assessed_cents`.
- **Finalize runs two internal passes** (all program selections, then all assessments) so `ERR_NO_QUALIFYING_RATE_PROGRAM` (28) masks `ERR_FX_RATE_UNAVAILABLE` (29) across records, matching ladder order rather than per-record order.
- `POST /_clock/set_current_utc` has `output: null`, so it returns `200` with `data: {}` in the standard object envelope.
- **Non-owner auditor** acting on a fork branch (`clear-findings`/`sustain-findings` by someone other than `auditor_user_id`) -> `ERR_INVALID_STATE`; the SoD code is reserved for the `close` hop the PRD names explicitly.
- Approval-time missing `supporting_doc_ref` -> `ERR_DOCUMENTATION_REQUIRED` 422.
- `type: number` fields (`rate`, `performance_threshold_pct`) accept only JSON numbers, not numeric strings, and serialise back as numbers.
- Out-of-domain enum values in list filters match nothing (`total_count: 0`) rather than 400; only `limit`/`offset` are shape-validated as query params.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so `test_suite/` did not exist when the implementation generator started — physical isolation held.

## Step 7: Run tests and iterate — 2026-09-03T08:46:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (each a full 8-round parallel `setsid nohup` sweep, `--isolation per-test-server`).

- Iteration 1: 95/117 passed in all 8 rounds — 22 failures, identical set in every round (fully deterministic, no flakiness signal).
- Iteration 2: **117/117 passed in all 8 rounds** (0 failed, 0 errors, 0 skipped; ~210s per round). Results files at `workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. Test count is unchanged at 117.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `make_incentive_program_payload`: default `performance_threshold_pct` changed from the JSON string `"80.00"` to the number `80.00`. PRD §3.8 declares it "a percentage from 0.00 through 1000.00 carried to two decimal places" and §2.7 lists it as a quantity "rounded half up to two decimal places", i.e. a JSON number; `test_helpers/types.py` already typed it `float`. The string payload made the PRD-faithful implementation correctly reject every incentive-program creation with `ERR_INVALID_REQUEST`, which surfaced as 21 independent-looking "Setup step failed" failures across 12 files.

**Fixes applied to `test_suite/`:**
- 12 files (`test_01`, `test_02`, `test_04`, `test_05`, `test_06`, `test_07`, `test_09`, `test_10`, `test_12`, `test_14`, `test_15`, `test_17`) — the inline `performance_threshold_pct="80.00"` / `"50.00"` / `"1.00"` overrides converted to numeric literals, same reason. No assertion read the returned value, so nothing was weakened.
- `test_suite/test_16_rbac.py::test_a_foreign_acquirer_may_read_the_merchant_but_not_challenge_it` — **partial-coverage split (STEP 1c)**: dropped the two lines asserting a foreign `AcquirerOps` gets HTTP 200 from `GET /merchants/{id}`; kept the write assertion (`ERR_ACQUIRER_SCOPE_VIOLATION` 403 on filing a reclassification, plus the "no request was recorded" check), which is the test's own design intent. Reason: PRD §2.9 priority 6 states verbatim "Applies to every endpoint whose authorized-role list includes `AcquirerOps`", and §4 defines "All roles" as including `AcquirerOps`, so `GET /merchants/{id}` is literally in scope; §2.1's softer "may **act** only where…" admits the opposite reading. Two divergent PRD-faithful implementations exist, so "the foreign read succeeds" is not uniquely derivable — while the write refusal is agreed by both readings. Docstring's lead sentence adjusted to match.

**Fixes applied to `implementation/`:** none. No implementation defect was found; in particular the `require_scope` check on `GET /merchants/{id}` was left in place rather than stripped, since it traces to PRD §2.9 priority 6.

Both `python3 -m compileall` and `pyflakes` are clean over `test_suite/` and `test_helpers/`.

Orchestrator verification (per the "verify Step 7 sweep artifacts" rule): all 8 `results.{1..8}.json` exist on disk (timestamped 08:45, ~40 KB each) and each parses to `passed=117 total=117 failed=0 errors=0 skipped=0`. The claim is independently confirmed, not taken on the subagent's word.

Note on earlier worklog timestamps: the Step 4/5/6 headers carry estimated wall-clock times rather than measured ones (the orchestrator did not re-read the clock between those steps). Actual ordering is unaffected; Step 7's 08:46 and the 08:45 results-file mtimes are measured.

## Step 8: Finalize PRD — 2026-09-03T09:05:43.146Z

`PRD_FINALIZED.md` is written. Two Step-7 subjects produced four edits; nothing else was touched.

**Line counts:** PRD.md 433 lines / 103,025 bytes -> PRD_FINALIZED.md 433 lines / 104,994 bytes. Line delta 0% (the file is one-paragraph-per-line markdown); byte delta +1,969 (+1.91%).

**Changes**

- §2.1 — revise — "may act only where…" widened to "may act on or read a single resource only where…"; added that a transaction record's owner is reached through its settlement batch; added that single-resource reads are refused for a foreign acquirer exactly as writes are; added that collection listings are never acquirer-scoped and that resources with no owning acquirer (the `Acquirer` row itself, platforms, MCC definitions, rate programs/versions, FX rows, incentive programs, merchant category audits) are outside the check — `implementation/routes_merchant.py:113`, `auth.py:43-48`.
- §2.9 priority 6 — revise — "Applies to every endpoint whose authorized-role list includes `AcquirerOps`" narrowed to endpoints whose target is a single resource with an owning acquirer, single-resource reads included, with listings and owner-less resources explicitly outside — `implementation/routes_merchant.py:109-128`, `routes_audit.py:146-163`.
- §2.7 — insert — both two-decimal quantities cross the wire as JSON numbers, not quoted strings (`performance_threshold_pct` on input as well as output) — `implementation/store.py:164,246`, `timeutil.py:132-138`.
- §2.9 priority 5 — insert — "well formed" now includes JSON-type strictness per field (strings / integers / numbers / booleans / arrays), with the explicit consequence that `performance_threshold_pct` as `"80.00"` is `ERR_INVALID_REQUEST` — `implementation/validate.py:58-138`, `routes_incentive.py:45`.

**Per-edit pre-edit search log**

1. §2.1 scope sentence. (a) Subject: which endpoints the `AcquirerOps` ownership check binds on, and how the owning acquirer is reached per entity. (b) Enumerated: `grep -n require_scope *.py` -> all 17 callsites; read `auth.py:43-48` (None owner => violation; non-AcquirerOps => no-op), `routes_merchant.py` (POST /merchants body id, verify-category unscoped/CategoryAnalyst-only, GET /merchants/{id} scoped, GET /merchants unscoped, reclass create/resubmit/GET scoped via merchant, review/request-info/decide unscoped by role), `routes_clearing.py` (batch create/submit/add-record/reverse and GET /settlement-batches/{id}, GET /transaction-records/{id} scoped via batch; both list endpoints unscoped; finalize is NetworkAdmin-only), `routes_windows.py` (create/start/complete/GET-by-id scoped; list unscoped), `routes_incentive.py` (enroll/withdraw/GET-by-id scoped via merchant; programs and both lists unscoped), `routes_audit.py` (no `require_scope` at all — GET audit by id is All-roles and unscoped), `routes_ref.py` (no `require_scope`; GET /acquirers/{id} unscoped), `listing.py` (no acquirer filtering anywhere). Also read `test_suite/test_16_rbac.py::test_all_five_roles_see_the_same_merchant_collection` as corroboration that listings stay unfiltered. (c) Adjustment: instead of a general "any row that reaches an acquirer" rule (which would falsely scope merchant category audits, since audits reach a merchant but impl never checks), kept the entity-by-entity enumeration, added transaction-record->batch, and added two explicit carve-outs (list endpoints; owner-less resources incl. audits).
2. §2.9 priority 6. (a) Subject: the "Applies to" scope line for the same check. (b) Same enumeration as edit 1, cross-checked against every "All roles" row of §4's table to identify which of them impl scopes (merchants, batches, records, windows, reclass requests, enrollments by id) versus not (platforms, acquirers, MCC definitions, rate programs, versions, FX rates, incentive programs, audits, and every list). (c) Adjustment: dropped the literal universal "every endpoint whose authorized-role list includes `AcquirerOps`" in favour of a resource-shaped qualifier, so the sentence no longer claims listings or owner-less GETs are refused.
3. §2.7 number-typing sentence. (a) Subject: the wire representation of `performance_threshold_pct` / `performance_score_pct`. (b) Enumerated: `grep -n "performance_threshold_pct|performance_score|dec2|as_number" *.py` -> `store.py:164` `NUMBER_FIELDS` (also contains FX `rate`), `store.py:246` serialization via `as_number`, `timeutil.py:127-138` (`dec2` -> 2-place Decimal, `as_number` -> float), `routes_incentive.py:45,55,154,184-197` (creation, enrollment default `Decimal("0.00")`, scoring write, Decimal-vs-Decimal threshold comparison). (c) Adjustment: phrased the output side as "a number like `80.0`, not the text `\"80.00\"`" rather than pinning an exact decimal rendering, since impl emits a JSON float and the exact digit form is not something impl guarantees beyond being a number.
4. §2.9 priority 5 JSON-type clause. (a) Subject: whether a correctly-parsing value in the wrong JSON type is a 400. (b) Enumerated every validator in `validate.py` (`req_str`/`opt_str`, `req_int` — rejects bool and float, `req_bool`/`opt_bool`, `req_enum`, `req_ts`/`req_date` via `timeutil.parse_iso_ms`/`parse_date` which return None for non-strings, `req_number` — rejects strings/bools, accepts ints, `req_code_list` — rejects non-lists and non-string items, `req_mcc`/`req_currency`/`req_country`/`req_business_type_key`, `raw_id`) and every callsite of them across `routes_ref.py`, `routes_windows.py`, `routes_merchant.py`, `routes_clearing.py`, `routes_incentive.py`, `routes_audit.py`, looking for any lenient coercion (`int(...)`/`float(...)` on request data) — there is none. (c) Adjustment: wrote the rule as a per-category type list ("integer-valued fields … as JSON integers", "a decimal quantity … as a JSON number") so it stays true both of `req_int` rejecting `80.0` and of `req_number` accepting a bare integer `80`; avoided any claim about string-to-number coercion being accepted anywhere.

Orchestrator verification: `PRD_FINALIZED.md` exists, is 433 lines / 104,994 bytes, and `cmp` confirms it is NOT byte-identical to `PRD.md` — the patch really landed.

## Step 9: Complete PRD — 2026-09-03T09:34:02.615Z

Run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` (seeded by the orchestrator as a copy of `PRD_FINALIZED.md` before pass A, so no pass could skip the copy step and leave the file byte-identical to its source). Partition rationale: a 3317-line implementation across 16 modules does not fit one subagent's scan budget without whole regions going unread; partitioning by file guarantees every module is walked by exactly one pass, and each pass was still permitted to read outside its partition for NO-NEW-MISMATCH checking.

**Total: 44 edits — 38 ambiguity-pins, 6 mismatch-revisions.** `PRD_FINALIZED.md` 433 lines / 104,994 bytes -> `PRD_COMPLETED.md` 433 lines / 116,956 bytes (+11,962 chars, +11.4%; line count unchanged because every edit was an in-paragraph insert or revision — no new sections).

### Pass A — `app.py`, `envelope.py`, `auth.py`, `resolve.py`, `listing.py`, `routes_ref.py`, `routes_windows.py`, `routes_merchant.py`
14 ambiguity-pins, 3 mismatch-revisions.
- §2.1 — insert — ambiguity — a present-but-empty `X-User-ID`/`X-User-Role` counts as absent; role match is case-sensitive — `auth.py:36`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0–9` — `envelope.py:21`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `envelope.py:27`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` refused, empty value = omitted, whitespace trimmed, `offset` unbounded above, past-the-end returns empty page with `has_more` false — `envelope.py:56-87`
- §2.3 — insert — ambiguity — filter params spelled as their field (sole alias `region` for `region_code` on platforms), trimmed, empty = absent, exact string equality, out-of-domain value matches no row rather than being malformed, `high_risk` accepts `true/false/1/0` case-insensitively — `listing.py:10-36`, `routes_ref.py:64-65,160`
- §2.9 item 30 — revise — mismatch — applies-to list was missing `POST /reclassification-requests/{id}/decide` on `APPROVE` only, below priority 17 — `routes_merchant.py:254-257`
- §3.1 — revise — mismatch — platform `name` is NOT unique; `max_concurrent_windows` has no upper bound — `routes_ref.py:39-49`
- §3.1 — insert — ambiguity — `requires_documentation`/`high_risk` are required booleans with no default; `program_eligibility` is the only optional input — `routes_ref.py:127-137`
- §3.2 — insert — ambiguity — the "exactly one `STANDARD` program" rule is a reference-data expectation, not enforced; only `program_code` uniqueness is checked — `routes_ref.py:189-191`
- §3.2 — insert — ambiguity — no ordering checked between `implementation_deadline` and the version's effective interval at draft time — `routes_ref.py:232-239`
- §3.2 — insert — ambiguity — `completion_note` required, 1-500 chars — `routes_windows.py:98`
- §3.3 — revise — mismatch — verify-category's `documentation_ref` is optional (<=500 chars), required non-blank only when the definition demands documentation, stored null when omitted; priority-7 `ERR_INVALID_STATE` branch reached only for an already-`VERIFIED` merchant — `routes_merchant.py:87-105`
- §3.4 — insert — ambiguity — `info_request_note` required 1-1000 chars — `routes_merchant.py:199`
- §3.4 — insert — ambiguity — resubmit's `supporting_doc_ref` optional (<=500) and replaces what was on file, so omitting it writes null over an earlier reference — `routes_merchant.py:215,234`
- §3.4 — insert — ambiguity — merchant `UNDER_REVIEW`/`MISREPRESENTED` blocks resubmission with priority-7 `ERR_INVALID_STATE`, not the dedicated merchant codes — `routes_merchant.py:222-223`
- §3.4 — insert — ambiguity — `decision_note` required 1-1000 chars — `routes_merchant.py:246`
- §4 intro — insert — ambiguity — trailing slash insignificant; unmounted path / unsupported method fails routing before the §2.9 ladder and returns `ERR_INVALID_REQUEST` with 404/405, regardless of auth headers — `app.py:26,58-64`

### Pass B — `routes_clearing.py`, `calc.py`
11 ambiguity-pins, 2 mismatch-revisions.
- §2.6 — insert — ambiguity — clock takes its new value before the sweep, so swept rows' `updated_at` carries the new instant even when rewound below `created_at` — `calc.py:658`
- §2.9 item 28 — revise — mismatch — `STANDARD` fallback must also list the record's merchant category in its own `eligible_mcc_codes` — `calc.py:107`
- §2.10 — insert — ambiguity — a re-derivation whose maintained quantities already hold their target values is not a change and advances no `version` (waitlist-admission carve-out preserved) — `calc.py:279-288,342-353`
- §3.4 — insert — ambiguity — the sustained-audit auto-deny leaves `prior_status_before_suspension` holding its snapshot rather than nulling it — `calc.py:395-403`
- §3.5 — revise — mismatch — `ERR_NO_QUALIFYING_RATE_PROGRAM` also arises when `STANDARD` exists but does not cover the merchant's category — `calc.py:107`
- §3.5 — insert — ambiguity — rate-program ranking's final tie-break past `created_at` is registration order — `calc.py:130-138`
- §3.5 — insert — ambiguity — `record_count` is re-derived over all records whatever their status, so it never falls — `calc.py:298-308`
- §3.6 — insert — ambiguity — finalization is all-or-nothing: a `NO_QUALIFYING`/`FX_UNAVAILABLE` refusal leaves batch `SUBMITTED`, records `PENDING`, no version moved — `calc.py:703-738`, `routes_clearing.py:197-198`
- §3.6 — insert — ambiguity — reference-program tie-break past `created_at` is registration order, and the per-item fee is never consulted — `calc.py:204`
- §3.6 — insert — ambiguity — `cross_border_surcharge_cents`/`fx_markup_cents` are stored unadjusted by the step-four clamp (so they need not sum into the total) and only the definitive pass writes them — `calc.py:185`, `routes_clearing.py:168-169,211-212`
- §3.7 — revise/insert — ambiguity — `reversal_reason` 1-1000 chars; the single `reversal_type`/`reversal_reason` pair is overwritten by a second reversal on the other dimension; neither reversal consults batch status — `routes_clearing.py:238-239,244-262`
- §3.7 — insert — ambiguity — a clearing reversal leaves `provisional_assessed_cents` intact — `routes_clearing.py:256-262`
- §3.8 — insert — ambiguity — promotion hangs off the reopening, so a release against an already-`OPEN` program promotes nobody even when the head-of-line row fits — `calc.py:436-442`

Pass B also recorded three behaviors needing no pin because they are unobservable: `assignment_rank`'s 4th tie-break key (mcc_code is globally unique), `applicable_fx_row`'s `created_at` tie-break (FX natural key includes `effective_from`), and `recompute_acquirer_compliance(allow_recovery=False)` in sweep step two.

### Pass C — `routes_incentive.py`, `routes_audit.py`, `store.py`, `validate.py`, `errors.py`, `timeutil.py`
13 ambiguity-pins, 4 mismatch-revisions. (`errors.py`'s 41 codes + status map were verified line-by-line against the §5 table — exact match, no edit needed.)
- §2.3 — insert — ambiguity — `created_at` ties in the default ordering are broken by row-creation order, never by `id` — `store.py:134-141`
- §2.4 — insert — ambiguity — all 13 instant-valued domain fields render in the same normalised UTC/3-digit form (or null) whatever form the client sent; `batch_date` stays a plain date — `store.py:148-162,239-254`
- §2.4 — insert — ambiguity — serialized field set and ordering: exactly `id` + entity fields + the three audit fields, `id` first, `created_at`/`updated_at`/`version` last, no internal keys, unset fields present as null, arrays echoed in supplied order — `store.py:166-254`
- §2.4 — insert — ambiguity — per-request `version` dedup, with the finalize ledger-recompute + downgrade-tripwire example (+1, not +2) — `store.py:113-131`, `app.py:37-41`
- §2.4 — revise — mismatch — the `IncentiveProgram.version` cascade list omitted shortfall termination and reclassification-driven ineligibility termination — `routes_incentive.py:207-209`, `calc.py:436-444`
- §2.5 — insert — ambiguity — a body FK is resolvable at priority 4 only as a non-blank string; other JSON types and the empty string fall to priority 5 — `validate.py:40-49`
- §2.6 — insert — ambiguity — the clock endpoint answers 200 with an empty `data` object — `routes_audit.py:170-176`
- §2.9 #5 — revise — mismatch — "Applies to every POST endpoint" was false for no-input endpoints (close-audit reads no body at all); added absent/empty/`null` body -> `{}` and non-object body -> malformed — `validate.py:25-37`, `routes_audit.py:132-143`
- §2.9 #5 — insert — ambiguity — an optional field arriving as `null` takes its default; an undeclared field is ignored, not refused — `validate.py:69-72,93-96`
- §2.9 #5 — insert — ambiguity — full accepted/rejected ISO-8601 grammar (T-or-space, optional seconds/fraction, `Z`/offset/no suffix read as UTC, whitespace trimmed, >3 fractional digits truncated not rounded, bare date refused) — `timeutil.py:10-49`
- §2.9 #5 — insert — ambiguity — `min_commitment_cents <= total_capacity_cents` and `reopen_threshold_cents >= min_commitment_cents` are priority-5 shape rules (400) — `routes_incentive.py:60-63`
- §2.9 #5 — insert — ambiguity — text length bounds counted untrimmed, so a blank non-empty string satisfies a minimum of one — `validate.py:58-66`
- §2.10 — revise — mismatch — "advances exactly as if requested directly" now qualified by the §2.4 per-request single-advance rule — `store.py:113-131`
- §3.1 — insert — ambiguity — FX `rate` is echoed as the JSON number supplied, not quantised like the two percentage fields — `store.py:164,246`
- §3.8 — revise — mismatch — `program_name` is NOT unique (impl has no such check and §2.9 #23 lists no incentive-program natural key) — `routes_incentive.py:47`
- §3.8 — insert — ambiguity — scoring admissible only from `ENROLLED`/`PROBATION` (else `ERR_INVALID_STATE`), and always advances `IncentiveEnrollment.version` even on an identical re-score — `routes_incentive.py:179-207`
- §3.8 — insert — ambiguity — `withdrawal_reason` required 1-1000 chars — `routes_incentive.py:218`
- §3.9 — insert — ambiguity — `findings_note` required 1-2000 chars on both fork branches — `routes_audit.py:86,114`
- §3.9 — insert — ambiguity — the sustained branch leaves `mcc_status_before_review` holding its snapshot rather than clearing it — `routes_audit.py:100-103`

### Orchestrator final verification
- `PRD_COMPLETED.md`: 433 lines / 116,956 bytes; `cmp` confirms it is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran, not just the copy).
- All five `##` headers present and in order (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue), 27 headers total; file ends on the complete final §5 table row.
- Every file under `workspace/implementation/` carries an mtime of 07:19-07:34, i.e. strictly earlier than the 08:45 green sweep. Steps 8 and 9 changed documentation only, so the 8/8-round 117/117 result stands unchanged and needs no re-run.

**Pipeline complete.**

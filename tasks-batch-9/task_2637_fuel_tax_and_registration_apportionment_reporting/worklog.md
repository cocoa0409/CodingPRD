# Worklog — task_2637_fuel_tax_and_registration_apportionment_reporting

## Step 1: Create task directory — 2026-09-03T23:17:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2637_fuel_tax_and_registration_apportionment_reporting` and its `workspace/` subdirectory. Index 2637 was pre-assigned by the orchestrating invocation; no scan of ./tasks/ was performed and no index was auto-allocated.

## Step 2: Generate scaffold — 2026-09-04T00:58:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2637_fuel_tax_and_registration_apportionment_reporting/`

```
-rw-rw-r-- 149170  SCAFFOLD.yaml                    2761 lines
-rw-rw-r-- 142310  SCAFFOLD_DIFFICULTY_DESIGN.yaml  1861 lines
-rw-rw-r-- 263916  SCAFFOLD_CORNER_DESIGN.yaml      4049 lines
```
(plus a pre-existing `worklog.md` and empty `workspace/` from the scaffold step)

Key-name constraints verified: `SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`. The other two files each have that single top-level key and nothing else.

## Content shape

- SCAFFOLD.yaml §1.0–§1.7: 15 entities, 50 endpoints, 9 calculations, 39 priority-ordered validations, 52 error ids, 4 roles (CarrierAdmin / MileageAnalyst / TaxPreparer / ComplianceOfficer, segregation-of-duties model), 2 OCC rules, difficulty_level `expert_plus`.
- §1.8: 18 instances across 9 rule blocks (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- §1.9: 89 entries over all nine claim-extraction-guide sections — 62 full test recipes plus 27 `excluded_because` stubs — distributed entities 14, state_machines 15, calculations 14, validations 19, endpoints 5, errors 10, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1.

## Final verification

```
Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  903

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Beyond the linter I ran a structural audit that caught one real defect in the already-written sections: 15 `excluded_because.difficulty_instance` citations used invented rule-block prefixes (`dual_variant_divergence`, `rounding_order_sensitivity`, `saturating_arithmetic`, `inclusive_exclusive_threshold`, `validation_priority_inversion`, `boundary_semantics`) instead of the actual §1.8 `rule_id` values. The instance names themselves were all correct; the prefixes were remapped to `dual_variant_calc`, `combinatorial_formula`, `boundary_precision_check`, `priority_pair_validation_conflict` and `resource_temporal_overlap`, and every citation now resolves to an existing `<rule_id> / <instance_name>`. Also confirmed: zero duplicate instance names across the two design files, no stub carries a `test_recipe`, and every full instance has `claim_type`, `distinguishing_aspect`, `setup`, `setup_api_calls`, `trigger` and `assert` (the single empty `setup_api_calls` is the deliberate empty-database 404 fixture).

The no-peeking constraint held throughout: nothing under any sibling `tasks/task_*/` was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-04T01:00:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T01:16:00.000Z

PRD.md is complete at `workspace/PRD.md`.

## File integrity
- `wc -l` = **489 lines**; written in 7 chunks (1 `Write` + 6 `cat >>` heredocs), never one giant Write, so no 64k-cap truncation.
- `tail -30` confirms it ends at a **genuine section boundary** — the final row of the §5 error table (`ERR_NO_ACCEPTED_MILEAGE | 422`), file ending in a newline, not mid-sentence.
- Sections present and in order: §1 Introduction, §2.1–§2.11, §3.1–§3.9, §4 Endpoint Definitions, §5 Error Code Catalogue. §2.2 is the byte-verbatim block from `section-2.2-response-structure.md`.
- Withheld files were never opened: no read, grep, or reference to `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.
- Meta-commentary guard: `'harder than expert'` -> **False**, `'difficulty'` (case-insensitive) -> **False**. The scaffold's `scenario` opening line was excluded.

## Hard Contract 1 — Field-Name Coverage: PASS
| Source | Required | Present | Missing |
|---|---|---|---|
| `entities[].fields` | 114 | 114 | 0 |
| `endpoints[].input` (POST) | 56 | 56 | 0 |
| `endpoints[].query_params` (GET) | 33 | 33 | 0 |
| `roles[].name` | 4 | 4 | 0 |
| `errors[].id` | 52 | 52 | 0 |

A second **strict** pass (exact backtick tokens, no sub-token credit) returned `STRICT missing: []`. Enum/state pass returned only `['1','2','3','4']` — the integer `filing_quarter`/`selection_quarter` values, rendered in prose as "1, 2, 3 or 4"; not identifiers.

## Hard Contract 2 — Rule Coverage: PASS
| Category | Scaffold | Covered |
|---|---|---|
| `validations[].priority` ordering | 39 | 39 — all appear in the §2.11 numbered precedence ladder (`not in 2.11 list: []`) |
| `concurrency_rules` (OCC) | 2 | 2 — both in §2.8 with exact endpoint, version field, error id, 412; plus the explicit statement that no other endpoint accepts a version field |
| Cross-entity cascades / `side_effects` | 25 endpoints with side effects | 25 — incl. the 4-hop reopening cascade (§3.6), PENDING->ACTIVE credential cascade (§3.7), transfer/reversal cascades (§3.8), re-selection cascade (§3.9) |
| `state_machines[].transitions` | 10 machines / 35 transitions | all states present (`missing states: []`), both dual dimensions on Vehicle and Carrier, cyclic ACCEPTED->GAP_FLAGGED covered |
| `validations[].applies_to` scopes | all | enumerated per rule — carrier scope (6 collections, §2.1), licence/IRP standing (§3.9), segregation (3 review steps, §2.9), jurisdiction-declared (5 operations, now named explicitly in §2.6), purchase lock (§3.4) |
| Field-level structured content | all | defaults, initial values, nullability, and bounds stated for every entity, incl. `bond_ceiling_amount` 5000.00, surcharge rate 0.0000, `prorate_months` 0, conserved `tax_paid_gallons_ytd` |
| Sibling-branch symmetry | all | ADDITION/DELETION/TRANSFER, ACTUAL/ESTIMATED basis, PREPARER_BASIS/AUDIT_BASIS, SUSPENDED/REVOKED, all 5 trip-review outcomes, both DISALLOWED paths, all 5 `credential_status` movements — equal density |
| `calculations` | 9 | 9, both variants each for the settlement and the apportioned fee; all constants, thresholds, clamps and rounding points stated in reconstruction-testable prose |
| `errors[]` narrative triggers | 52 | 52 — every id has a trigger stated outside the §5 table (`no narrative mention: []`) |

## Hard Contract 3 — §3 Path Purity: PASS
986 backtick tokens scanned inside §3: `/`-leading tokens **0**, bare HTTP-method tokens **0**, method+path tokens **0**. All 50 scaffold paths appear only in the §4 table (`missing from §4: []`).

## Scaffold ambiguities resolved (implementer-facing decisions baked into the prose)
- `audit_flag` threshold 0.2500 vs 0.1500 -> **0.1500**, strictly greater.
- Vehicle uniqueness pair vs triple -> **triple including `registration_year`**.
- `reported_distance_miles` `> 0.0` vs `>= 0.0` -> **`>= 0.0`**.
- `valid_to_date` "always Dec 31" vs supplied-or-default -> **supplied overrides, else Dec 31**.
- AuditSelection review fields "start at zero" vs "null until review" -> **null**.
- State preconditions with no nominated error id mapped to the existing `ERR_INVALID_APPLICATION_STATE` / `ERR_INVALID_TRIP_STATE` rather than inventing ids; `cdl_number` uniqueness stated as a constraint without an error id, since the scaffold nominates none.

### Orchestrator truncation-guard verification (independent of the subagent's claim)
Re-checked directly: 489 lines / 105083 bytes; `## 5. Error Code Catalogue` is the last section and the file ends on the 52nd error-table row; §4 table holds exactly 50 endpoint rows; `grep -ci 'harder than expert|difficulty|expert_plus'` = 0. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T03:15:00.000Z

The unit-test infrastructure for task_2637 is complete.

## Output locations (both at the TASK ROOT, nothing under `workspace/`)
- `test_helpers/`
- `test_suite/`

`find workspace -name test_helpers -o -name test_suite` returns nothing.

## Final state: 138 tests across 17 files, `pytest --collect-only` collects all 138 with zero errors

test_helpers (3,089 lines): `__init__.py` 54, `api_client.py` 498, `api_errors.py` 151, `assertions.py` 572, `constants.py` 126, `factories.py` 240, `fixtures.py` 978, `test_users.py` 65, `types.py` 405.

test_suite (10,090 lines): `conftest.py` 60, `test_01` 499/7 tests, `test_02` 491/9, `test_03` 496/9, `test_04` 568/10, `test_05` 397/8, `test_06` 459/7, `test_07` 598/9, `test_08` 453/7, `test_09` 588/10, `test_10` 716/12, `test_11` 719/10, `test_12` 614/5, `test_13` 1091/14, `test_14` 497/5, `test_15` 999/10, `test_16` 351/3, `test_17` 494/3.

## Work completed this session
1. **`test_17_cross_cutting_and_consistency.py`** (new, 494 lines, 3 tests) — the last three non-stub queue-B instances: the stale-application-version supplement collision (412, one supplement survives, fresh version == snapshot+1, fee basis still 2350.80/1 unit), the stale-carrier-version second prepare (412, IL -6.27 + IN 8.80 = 2.53, refusal voids nothing — 2 lines before, 2 ACTIVE + 2 VOIDED after the legitimate re-prepare), and the invoice cascade read straight out of the INVOICE response body (2 units ACTIVE on 2026-08-01, 100000.0 fleet miles, IL 0.600000/3348.00 + IN 0.400000/1353.60 = 4701.60, re-read byte-identical).

2. **Fixed 27 pre-existing non-verbatim PRD citations** in `test_01`-`test_10`. Every one was the same defect class: a quotation truncated mid-sentence with a period appended by the author (e.g. the surcharge, penalty-floor, bond-ceiling, risk-threshold and reversal sentences), plus one fabricated span in `test_06` ("the numerator is the sum of the `leg_miles` of the `ACTIVE` `TripJurisdictionLeg` rows..." appears nowhere in the PRD — replaced with the real §3.5 step-one sentences), and one dangling ellipsis in `test_10`. All are now full verbatim PRD sentences.

## Verification (all green)
- `pyflakes`: clean across `test_suite/` (4 harmless unused re-export imports remain in `test_helpers/`, untouched).
- Citation verifier over all 18 files: **0 failures**.
- Design tags: 138 tests, each with exactly one `Design:` line as the last docstring line; **0** tags resolve to nothing, **0** tags point at an `excluded_because:` stub.
- Coverage: all **18/18** difficulty instances have >=2 tests; all **62/62** non-stub corner instances (89 total - 27 stubs) have >=1 test -> 80 distinct instances covered, no skipped instances.
- All 27 stubs' `difficulty_instance:` cross-references resolve to real rule_ids.
- No `skip`/`skipif`/`xfail`, no mocking, no mention of "scaffold".

### Orchestrator path verification
`ls -d test_helpers test_suite` both resolve at the task root; `find workspace -name test_helpers -o -name test_suite` is empty. 18 files in test_suite/, 9 in test_helpers/.

## Step 6: Generate implementation — 2026-09-04T03:15:30.000Z

The implementation is complete and smoke-tested.

## Files written
`workspace/implementation/`

| file | lines |
|---|---|
| `app.py` | 73 |
| `common.py` | 657 |
| `serializers.py` | 274 |
| `calc.py` | 487 |
| `routes_ref.py` | 373 |
| `routes_mileage.py` | 462 |
| `routes_returns.py` | 316 |
| `routes_registration.py` | 956 |
| `requirements.txt` | 1 |
| `start.sh` | 10 |
| **total** | **3609** |

## Structure
- `app.py` — creates the Flask app, registers the four blueprints, and installs handlers for `ApiError` (envelope + its own HTTP status), 400/404/405/415 and a catch-all 500. `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True, use_reloader=False)`.
- `start.sh` — `cd`s to its own dir, installs Flask only when the import fails (an unconditional `pip install` on every per-test reboot causes boot contention under 8 concurrent rounds), then `exec python3 app.py` in the foreground.
- Storage is in-memory only: `common.DB = Store()` holds 15 plain dicts and is rebuilt empty at import. Verified by grep that there is no sqlite, no `open(`, no `json.dump`, no `/tmp` anywhere in the package — and nothing is seeded.

## Smoke test (port 17637, single PID, killed by PID + `fuser -k 17637/tcp`)
Went well beyond a couple of curls — drove a full end-to-end scenario through 30+ endpoints and all four blueprints, and the server logged no traceback:
- envelope shape correct (`meta.api_request_id` `req_...`, timestamp with exactly 3 fractional digits, `limit/offset/total_count/has_more` on lists, `response_type`)
- 401 with no headers, 403 `ERR_FORBIDDEN_ROLE`, 404 on an unknown path, 400 `ERR_INVALID_REQUEST` for a numeric field sent as a string / unknown field
- jurisdictions -> weight-group fees -> carrier -> vehicle -> driver -> application -> 3 distance-schedule lines -> submit -> review(INVOICE) (`base_fee_total` 1800.00, `apportion_frozen_at` from the logical clock, vehicle PENDING->ACTIVE with `activated_on_date`) -> issue-credentials (3 credentials, `credential_status` derived to ISSUED) -> distribute
- fleet-change-request ADDITION with OCC -> decide APPROVE (`fee_delta` 1050.00 from a 7-month proration) -> reverse
- trip capture -> gap detection (`gap_miles_from_previous` 400.0 -> GAP_FLAGGED) -> review ACCEPT -> fuel purchase -> return prepare (`fleet_mpg` 6.0, 2 jurisdiction lines incl. the IN surcharge) -> review FILE
- audit selection risk scoring (85 -> SELECTED, `carrier.audit_flag` true, ratio 0.4545) -> retention-review, which correctly ran the full cascade: `post_review_risk_score` 100 -> return re-settled on AUDIT_BASIS to `AUDIT_ADJUSTED`, IFTA licence ACTIVE->SUSPENDED with `suspension_count` 1, the `IFTA_LICENSE_COPY` credential VOIDED with `LICENSE_SUSPENSION`, drivers left ACTIVE (deactivation only fires on revoke)
- error paths hit naturally and returned the right ids/statuses: `ERR_DUPLICATE_JURISDICTION` 409, `ERR_DUPLICATE_USDOT_NUMBER` 409, `ERR_STALE_CARRIER_VERSION` 412, `ERR_RECONSTRUCTION_WINDOW_CLOSED` 422, `ERR_INVALID_TRIP_STATE` 409, `ERR_AUDIT_SELECTION_NOT_SELECTED` 409, `ERR_NO_FILED_RETURN_FOR_PERIOD` 409

Port 17637 is free again and the temp smoke files were removed. No broad `pkill` was ever used.

Design note flagged by the impl generator: `Carrier.audit_flag` is implemented as the hard derivation `unsubstantiated_mileage_ratio > 0.1500` (SCAFFOLD line 1530), so a later ratio recompute can clear a flag that an audit selection set — spec-faithful but an interaction a test could read either way.

### Note on Step 5/6 concurrency
Steps 5 and 6 were launched in a single assistant message so the implementation generator started before `test_suite/` existed on disk, guaranteeing physical isolation from the tests.

## Step 7: Run tests and iterate — 2026-09-04T03:28:00.000Z

All 8 rounds are green at **138/138**. The task converged in 2 iterations, with zero changes to `implementation/` — all three defects were test-side.

## Summary

**Iterations run:** 2 (iteration 1 sweep: 132/138 in all 8 rounds; iteration 2 sweep: 138/138 in all 8 rounds).

**Tests deleted:** none. All 6 failing tests passed STEP 1a (PRD verbatim-covers) and STEP 1b (unique derivability); every failure was a STEP 2 test-vs-PRD consistency defect.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `accept_trip()` and `reject_trip()`: added the `review_note` pass-through to the underlying `review_trip()`. PRD §3.3 states the reviewer "may attach an optional `review_note`", but the two convenience wrappers dropped the parameter, so `test_11::test_a_rejected_trip_is_terminal_and_a_second_review_cannot_revive_it` died with `TypeError: reject_trip() got an unexpected keyword argument 'review_note'` before reaching any assertion.

**Fixes applied to `test_suite/`:**
- `test_05_validation_priority_pairs.py` — the `accepted_reconstruction` fixture and `test_the_segregation_rule_does_surface_once_the_state_condition_is_clear` both captured their trip as the vehicle's *first* trip, so per PRD §3.2 ("If no such trip exists, `gap_miles_from_previous` is 0.0") it was born `CAPTURED`, and the implementation correctly refused the reconstruction with `ERR_INVALID_TRIP_STATE`. Both docstrings already declared the intent ("behind a 100.0-mile gap") and the reconstructed legs summed to 600.0 = 500.0 delta + 100.0 gap, which only reconciles under §3.3 if that gap exists. Added the missing chronological predecessor (`2026-06-04`, odometer 599800.0->600000.0) so the trip under test carries the intended 100.0-mile gap and is born `GAP_FLAGGED`. Fixed 4 tests.
- `test_13_validations.py::test_a_scheduled_jurisdiction_with_no_weight_group_fee_row_is_rejected_at_invoice` — asserted `apportioned_vehicle_count=0` on a `SUBMITTED` application whose carrier holds one `PENDING` unit. PRD §3.7 says the count is "computed immediately from the carrier's power units for that `registration_year` whose `vehicle_status` is either `PENDING` or `ACTIVE`" and is "recomputed" on submit — and submission itself requires the count be "at least 1", so 0 is self-contradictory with the submit the test performs. Corrected the expectation to 1; the test's actual subject (nothing frozen, no percentage written, unit still `PENDING`) is untouched.

**Fixes applied to `implementation/`:** none. No implementation check was weakened or removed, no endpoint/field/side-effect was added, and storage remains in-memory only (verified: no sqlite, `open(`, `json.dump`, or `/tmp` anywhere in the package).

**Final per-round results:** rounds 1-8 all `138/138` passed.

### Orchestrator independent verification of the sweep artifacts
Rather than trust the subagent's claim, I read all 8 `workspace/implementation/results.$i.json` directly (all present, ~48 KB each, timestamped 03:26): every round reports `passed=138 total=138 failed=0`. Artifacts confirmed real.

### Step 8 gating decision
The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 made 1 `test_helpers/` fix and 2 `test_suite/` fixes across 2 iterations, so the condition is not met and **Step 8 runs**. Note in advance that with 0 `implementation/` fixes the expected Step 8 diff is small — the Step 7 items are fixture/expectation bugs, which per the skill's method are not necessarily PRD silences; Step 8 must patch only where the impl pinned a choice the PRD left open.

## Step 8: Finalize PRD — 2026-09-04T03:31:00.000Z

**Result: zero edits.** `workspace/PRD_FINALIZED.md` exists and is a **byte-identical copy** of `PRD.md` (both 489 lines, md5 `4b8e61b5e2f0b33fff9d64e7e4220006`, `cmp` clean). 0.00% delta.

## Why no edit was warranted

All three `<step_7_diff>` items are test/fixture defects against behavior PRD.md *already* uniquely determines. Each was checked against the implementation:

**Item 1 — `test_helpers/fixtures.py` `review_note` pass-through.**
Subject: the optional `review_note` on a trip review. Impl paths enumerated: `routes_mileage.py:268-275` (`review_trip`: `reject_unknown(body, {"decision","review_note"})`, `need_str(body,"review_note",required=False)`), plus the two parallel review endpoints that accept the same field — `routes_returns.py:251-253` (return review) and `routes_registration.py:306-308` (application review) — and `serializers.py` (grepped: no `review_note` on any serialized row, so it is validated and discarded, never persisted). PRD §3.3 already states the reviewer "may attach an optional `review_note`", and §3.6/§3.7 say the same for the other two endpoints; PRD never claims the note is stored, so impl's accept-and-discard is consistent. Pure wrapper bug in the helper — no PRD silence.

**Item 2 — `test_05` fixture born `CAPTURED` instead of `GAP_FLAGGED`.**
Subject: predecessor selection / `gap_miles_from_previous` for a vehicle's first trip, and the reconstruction reconciliation target. Impl paths enumerated: `calc.py:164-168` (`gap_from_previous` -> `miles(ZERO)` when `predecessor_trip` is None), `calc.py` `predecessor_trip` (chronological), `routes_mileage.py:120-124` (negative gap -> shape error, matching §2.11's odometer-rollback clause), `routes_mileage.py:153` (`"GAP_FLAGGED" if gap > calc.GAP_TOLERANCE_MILES else "CAPTURED"`, `GAP_TOLERANCE_MILES = D("5.0")` at `calc.py:28`), `routes_mileage.py:241` (reconstruction expects `odometer_delta_miles + gap_miles_from_previous`), and `routes_mileage.py:284` (the `CAPTURED`-accept gap guard). Every one of these is already stated verbatim in PRD §3.2 ("If no such trip exists, `gap_miles_from_previous` is 0.0"; strict `>` 5.0) and §3.3 (reconstruct only from `GAP_FLAGGED`; reconcile to delta + gap). Step 7 fixed the fixture by adding the missing chronological predecessor — exactly what the PRD requires. No PRD silence.

**Item 3 — `test_13` asserted `apportioned_vehicle_count=0` on a `SUBMITTED` application.**
Subject: derivation of `apportioned_vehicle_count`. Impl paths enumerated: `calc.py:102-106` (counts the carrier's units for the year in `PENDING` or `ACTIVE`), `routes_registration.py:153` (computed at DRAFT creation), `routes_registration.py:277,290` (recomputed and stored on submit, and the `>= 1` submit gate), and `routes_registration.py:522-523` (the only other mutation: +/-1/0 delta on fleet-change approval, and the reversal restore at `:666-672`). PRD §3.7 already pins the creation value, the submit recompute, and the "at least 1" gate; §3.8 pins the delta. The old expectation of 0 was self-contradictory with the submit the test performs. No PRD silence.

No implementation fix was applied in Step 7, no endpoint/field/side-effect was added, and no impl behavior was found that PRD.md leaves open or describes differently at these three sites — so per the method note, the correct output is the unmodified copy.

### Orchestrator note on Step 9 strategy
Because Step 8 legitimately produced a byte-identical file, Step 9 is the only step that will actually change the PRD, and it must scan all 3,609 impl lines. A single-pass Step 9 over an implementation this large tends to under-scan and emit a near-identical file. Step 9 is therefore being run as **three sequential file-partitioned passes** over the same output file (`PRD_COMPLETED.md`), each pass owning a disjoint slice of `implementation/`: Pass A = `app.py` + `common.py` + `serializers.py` + `routes_ref.py`; Pass B = `routes_mileage.py` + `routes_returns.py` + the fuel-tax half of `calc.py`; Pass C = `routes_registration.py` + the registration/fee half of `calc.py`. Passes run sequentially, not concurrently, because they edit one file.

## Step 9: Complete PRD — 2026-09-04T04:05:00.000Z

Run as **three sequential file-partitioned passes** over one output file, per the strategy note in the Step 8 entry. Total: **62 edits** (53 ambiguity-pins, 9 mismatch-revisions). `PRD_FINALIZED.md` 489 lines / 105,083 bytes -> `PRD_COMPLETED.md` 500 lines / 120,991 bytes (+11 lines, +15,908 bytes, +15.1%); 117 changed diff lines. Nearly every edit was in-paragraph, so the line count barely moved while the byte count grew substantially — the intended shape for a "minimal patch, no new sections" pass.

### Pass A — `app.py`, `common.py`, `serializers.py`, `routes_ref.py` (25 edits: 22 ambiguity, 3 mismatch)
Cross-cutting machinery. Pinned: whitespace-trimmed headers; carrier-scope list exhaustive and **no read is ever scope-checked**; `api_request_id` = `req_` + exactly 20 chars of `[A-Z0-9]`; `api_request_timestamp` from **real** server time, not the logical clock; pagination meta only on list responses; 404 `ERR_NOT_FOUND` / 405 `ERR_METHOD_NOT_ALLOWED` / 500 `ERR_INTERNAL` decided by routing *before* header checks; non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; date sort keys compared as stored strings; filters exact case-sensitive with uninterpretable values matching nothing (200/empty, not an error); `id` a canonical v4 UUID; `created_at` strictly increasing so `created_at` ASC is a total order; client-supplied dates echoed byte-for-byte; quantisation-on-store but bounds checked pre-quantisation, and quantities serialising as JSON numbers so `100.00` -> `100.0`; strict JSON typing (no numeric strings, bool never a number, whitespace-only string is empty, explicit `null` == omitted, no body == `{}`); nothing is seeded at boot.
Mismatches corrected: `base_jurisdiction_code` is **not** validated against declared jurisdictions; `cdl_number` has **no** uniqueness rule (PRD had asserted one with no error code to back it); and 201 is returned only by a POST that creates the resource its own path names.
Added five §5 rows: `ERR_JURISDICTION_NOT_FOUND` 404, `ERR_WEIGHT_GROUP_FEE_NOT_FOUND` 404, `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500.

### Pass B — `routes_mileage.py`, `routes_returns.py`, fuel/return half of `calc.py` (17 edits: 14 ambiguity, 3 mismatch)
Pinned: `legs` element shape and that two legs may name the same jurisdiction; `odometer_delta_miles` rounds the difference of the **as-supplied** readings while each reading is separately quantised, so the stored delta need not equal the difference of the stored readings; `ERR_RECONSTRUCTION_SUPPORT_MISSING` reported only after the status check, with malformed-but-present input staying a 400; every non-tabulated status/decision pairing -> `ERR_INVALID_TRIP_STATE`; `review_note` validated but neither persisted nor echoed (all three review endpoints); a rounded `fleet_mpg` of exactly 0.00 skips the division and yields `taxable_gallons` 0.000 with nothing refused; filing writes nothing outside the return row, the purchase freeze resting entirely on the later disallow guard; the reopening cascade deliberately leaves `total_tax_paid_gallons`, `settlement_basis`, `prepared_by_user_id` as the superseded preparation left them and does **not** clear `reconstructed_by_user_id` (unlike a §3.3 rejection), keeping that analyst barred from the next review.
Mismatches corrected: trips sort on `trip_start_utc` **parsed and normalised to UTC** — the one exception to §2.3's string comparison; purchase auto-acceptance requires a `receipt_reference` with at least one non-whitespace character, not merely present; and the risk-rescore hop runs on **every** correction regardless of `audit_flag`, writing the recomputed score back even when the record stays `NOT_SELECTED` and re-setting `audit_flag` at >=70 even if an earlier hop cleared it.

### Pass C — `routes_registration.py`, registration half of `calc.py` (20 edits: 17 ambiguity, 3 mismatch)
Pinned: zero-denominator clamp (all-zero actual distance -> percents 0.000000, fees 0.00, nothing refused); the fee multiplier is the `apportioned_vehicle_count` frozen **at submission** and never recomputed at invoicing, so a unit enrolled in between is activated but not priced; credential creation order `DECAL_SET`, `CAB_CARD`, `IFTA_LICENSE_COPY` unit-by-unit; `valid_from_date`/`valid_to_date` never checked against each other; issue-credentials responds with the **application**, not the credentials; the "no active unit" state error is evaluated *after* the licence check so `ERR_CARRIER_LICENSE_INACTIVE` wins when both hold; supplement units need not belong to the application's carrier; a rejected supplement leaves `prorate_months` at 0 as well as `fee_delta`; DELETION and TRANSFER each advance a unit's `version` by exactly 1 (one combined mutation), resolving §2.10's "once per mutation" ambiguity; a reversal **re-stamps `decided_by_user_id`** with the reversing officer; an already-`REVOKED` licence is untouched at any score.
Mismatches corrected: §2.4's "line-shaped entities are never edited in place" was false — invoicing fills `apportion_percent`/`jurisdiction_fee_amount`/`effective_distance_miles` onto existing `ACTIVE` rows (reworded to "never versioned"); the drivers hop's "credentials already distributed are left exactly as they are" contradicted bullet 1's voiding of distributed `IFTA_LICENSE_COPY` rows (narrowed to "no credential moves in this hop", and pinned that voided copies keep `distributed_to_driver_id`/`distributed_at`).
**Lead 1 from Pass B resolved:** confirmed — `_resettle_on_audit_basis` (`routes_registration.py:838`) does rewrite `total_tax_paid_gallons`, which §3.9's field list omitted; added, with the note that the recomputed gallons normally reproduce the filed figure because a filed quarter's purchases are locked against disallowance.
**Lead 2 resolved:** all 12 `201` sites audited (routes_ref x5, routes_mileage x2, routes_returns x1, routes_registration x4). Pass A's generalisation held, but `POST /registration-applications/{id}/distance-schedule` is the API's only nested 201, so it is now named explicitly. Every other registration POST (submit, review, issue-credentials, decide, reverse, distribute, retention-review) returns 200 — including issue-credentials, which creates Credential rows as a transition side effect.

### Orchestrator final verification
- `PRD_COMPLETED.md`: 500 lines, ends at `| ERR_INTERNAL | 500 |` — the last row of the §5 table, a genuine section boundary. Not truncated.
- Structure intact: §1, §2.1-§2.11 (all 11), §3.1-§3.9 (all 9), §4 endpoint table **50 rows**, §5 catalogue **57 rows** (52 original + 5 added by Pass A).
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` differs (117 diff lines) — the scan genuinely ran; it did not silently no-op.
- **Test/implementation code is byte-for-byte what produced the green sweep.** Every file under `workspace/implementation/` and both test directories has an mtime at or before 03:22, while the passing 8-round sweep's `results.*.json` are stamped 03:26. Steps 8 and 9 touched only `PRD_FINALIZED.md` and `PRD_COMPLETED.md`. The 8x 138/138 result therefore still describes the delivered artifacts exactly, and the sweep was deliberately not re-run — re-running would only risk overwriting known-good artifacts with a load-contended round on a 32-pipeline host.

**PIPELINE COMPLETE.** Final state: 138 tests, 8/8 rounds at 138/138, 0 tests deleted, 0 implementation fixes, PRD completed to zero known residual silence or mismatch.

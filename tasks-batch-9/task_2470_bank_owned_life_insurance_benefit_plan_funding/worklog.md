# Worklog — task_2470_bank_owned_life_insurance_benefit_plan_funding

## Step 1: Create task directory — 2026-09-02T21:07:58.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2470_bank_owned_life_insurance_benefit_plan_funding` and its `workspace/` subdirectory. Index 2470 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per instruction — 32 concurrent pipelines on this host would collide).

## Step 2: Generate scaffold artifacts (§1.0–§1.9) — 2026-09-02T23:05:00.000Z

Wrote the three scaffold files from the scenario text plus the scaffold-generator specification only (no sibling task under `tasks/` was inspected, per the hard constraint).

- `SCAFFOLD.yaml` — §1.0–§1.7. 15 entities, 11 state machines, 2 §1.2.1 concurrency rules, 10 calculations, 29 ordered validations, 85 endpoints, 37 errors, 7 roles. Above the §0.4 Expert band on every axis (entities 15, endpoints 85, errors 37, 11 machines including a two-dimension parallel claim machine and cyclic diligence/board loops). Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single top-level key. 9 rule_id blocks × 2 differentiated instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single top-level key. 59 instances over all nine claim-extraction-guide sections (entities 12, state_machines 11, calculations 9, validations 8, endpoints 5, errors 5, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1), of which 13 are `excluded_because:` stubs citing §1.8 instances by name. Every one of the 37 §1.6 error ids is triggered by at least one §1.8 or §1.9 instance.

All formula-derived assert literals were computed with Python `Decimal` + `ROUND_HALF_UP` against the §1.3 formulas and constants.

`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2470_.../` →

```
Coverage
  §1.5 endpoints declared:    85
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  781

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Post-lint checks: 77 instance names unique across the union of both design files; every `${var}` in every path/payload/as_user_id/assert is bound by an earlier `captures:` in the same instance (0 unbound); one §1.4 edit was required during §1.9 authoring — validation priority 8's `applies_to` now also covers `POST /nqdc-liabilities` against a FROZEN or TERMINATED `NqdcPlan`, which had no declared error mapping.

## Step 3: Copy shared files — 2026-09-02T22:48:53.504Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`. Verified Step 2 outputs on disk: SCAFFOLD.yaml (3182 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (2072), SCAFFOLD_CORNER_DESIGN.yaml (2668).

## Step 4: Generate PRD — 2026-09-02T23:20:00.000Z

NOTE — first attempt failed. The initial doc-generator subagent died on an API error mid-run and left a truncated `PRD.md` (263 lines, stopping mid-document at "### 3.6. The Regulatory Notification Fork..." with a literal `<!--APPEND-->` placeholder at EOF; §4 endpoint table and §5 error catalogue entirely absent). Per the orchestration instruction, the truncated file was DELETED and the PRD regenerated from scratch — not hand-patched. The retry prompt added an explicit anti-truncation contract (many small append passes, no giant single Write, no authoring markers, and a mandatory five-point self-verification before exit).

Verbatim summary from the successful (second) doc-generator subagent:

All verification checks now pass. The two earlier "failures" were confirmed artifacts of my checker script (unbalanced-backtick desync at the four §2.2 code fences, and the §4 table splitting Method and Path into separate columns, which is the format SKILL.md mandates). Both were fixed in the script; no content was missing from the PRD.

## Deliverable

`workspace/PRD.md`

- **444 lines / 103,649 characters**, ends with a trailing newline.
- **Last section: `## 5. Error Code Catalogue`** — the file's final line is the 37th and last error row (`ERR_SURRENDER_EXCEEDS_CASH_VALUE | 422`). The document terminates at a real section boundary; nothing is cut mid-sentence.
- Built in 13 incremental append passes plus targeted edits; no giant single Write, and no authoring marker was ever written.

Structure: §1 Introduction; §2 Global Specifications with 11 subsections (RBAC, verbatim §2.2 response envelope, pagination, identity/timestamps/version, logical clock, monetary + basis-point rounding, capital snapshots as shared denominator, segregation of duties, OCC on carriers and policies, cascades/conservation invariants, validation order and nested path resolution); §3 Business Logic with exactly 9 subsections (carrier onboarding/diligence → insurable interest and consent → purchase drafting and capacity reservation → regulatory notice/concurrence/issuance → product registration and statement monitoring → NQDC liability matching and funding posture → death claims and beneficiary split → disposition analysis and tax → annual risk assessment and board reporting); §4 endpoint table (4 columns, 85 rows); §5 error table (2 columns, 37 rows).

## Verification results (all five reported as required)

1. **Line/char count:** 444 lines, 103,649 chars.
2. **`tail -30`:** complete prose/table content, ends on the final §5 error row; §5 has exactly 37 data rows and §4 exactly 85 data rows (verified by row count excluding header and separator).
3. **All 85 endpoints present:** `85 required, 85 present, missing=[]`. Each scaffold endpoint matched a unique §4 row whose Method cell equals the method and whose Path cell equals the backticked path exactly.
4. **All 37 error ids present:** `37 required, 37 in §5 table, missing_table=[], missing_anywhere=[]`.
5. **Authoring-marker grep** for `APPEND\|TODO\|TBD\|placeholder\|continued`: **no matches** (grep exit 1).

## Hard Contract reports (summary only — not written into PRD.md or any sibling file)

- **Contract 1 — Field-Name Coverage: PASS.** 129/129 `entities[].fields[].name` identifiers and 71/71 endpoint `input`/`query_params`/`path_params` identifiers appear verbatim in backticks; both missing-sets empty.
- **Contract 2 — Rule Coverage: PASS.** All 11 state machines' state values appear (0 missing across every entity, including both `DeathBenefitClaim` dimensions). All 29 validations, both `concurrency_rules` (`expected_carrier_version` → `ERR_STALE_CARRIER_VERSION` 412; `expected_policy_version` → `ERR_STALE_POLICY_VERSION` 412), and all 10 calculations are expressed as precise natural-language prose with every constant *value* stated (verified programmatically: only two flagged, `250,000.00` and `25,000,000.00`, both confirmed present at PRD lines 172/186 and 188 in comma-formatted form). Calculation names, constant identifiers and entity class names are deliberately *not* echoed verbatim — the spec requires the semantics in prose, not the scaffold's internal symbols.
- **Contract 3 — §3 Path Purity: PASS.** 969 backtick tokens scanned in §3; zero start with `/`, zero are bare HTTP methods, zero combine method+path.

Two authoring notes worth passing on: (a) the `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` withholding constraint was honored — neither file was opened, grepped, or referenced; (b) for the several scaffold transitions whose preconditions carry no dedicated error id (carrier reinstate/terminate, product clear-watch, plan unfreeze/terminate, the branch-A/branch-B concurrence guards, beneficiary-allocation void) I consistently specified rejection with `ERR_INVALID_STATE_TRANSITION` and said so explicitly in the prose, so the implementer is not left guessing.

Orchestrator-side independent re-verification: `wc -l` = 444; tail shows the final 12 §5 error rows ending at `ERR_SURRENDER_EXCEEDS_CASH_VALUE | 422`; `grep 'APPEND\|TODO\|TBD'` returns nothing; section index shows §1, §2.1–§2.11, §3.1–§3.9, §4, §5 all present. Truncation guard satisfied.

## Step 6: Generate implementation — 2026-09-03T00:12:00.000Z

NOTE — first attempt failed. The initial implementation-generator subagent hit a transient API error immediately after reading the spec, before writing any file; `workspace/implementation/` was left empty (nothing salvageable). Relaunched with an added resilience instruction: write the implementation incrementally as multiple small-to-medium modules rather than one enormous Write, so partial progress survives a mid-run failure. Step 5 was still running at relaunch time, so the concurrency-based isolation between test-gen and impl-gen was preserved.

Verbatim summary from the successful (second) implementation-generator subagent:

The implementation for task_2470 is complete and verified.

## Boot verification (fresh process via `start.sh`)

Launched with `PORT=19470 bash start.sh &` from `workspace/implementation/`, then probed over real HTTP:

- `GET /carriers` → **200** with the exact array envelope: `{"meta":{"api_request_id":...,"api_request_timestamp":...,"limit":10,"offset":0,"total_count":0,"has_more":false},"response_type":"array","data":[]}` — and `data: []` confirms **nothing is seeded**.
- `POST /capital-positions` → **201** object envelope, `created_at` `2026-08-01T00:00:00.000Z` (logical clock epoch, not wall clock).
- No auth headers → **401** `ERR_UNAUTHENTICATED`; wrong role → **403** `ERR_UNAUTHORIZED`; unknown path → **404** `ERR_RECORD_NOT_FOUND`; `limit=0/101`, `offset=-1`, bad enum, malformed datetime → **400** `ERR_INVALID_REQUEST`; unknown id → **404** `ERR_CARRIER_NOT_FOUND`.
- Both test servers I started (ports 17470, 19470) are now killed; other agents' servers (17471, 18462) were left untouched.

## Route count: 85 / 85 — none missing, none extra

Programmatic diff of `app.url_map` against every `method`/`path` pair in `SCAFFOLD.yaml` (with `<var>` normalized to `{id}`): `implemented 85, spec 85, missing [], extra []`.

## End-to-end behavioral run

A scratch smoke script (`/tmp/smoke2470.py`, outside the implementation tree) drives all 13 domain areas through the Flask test client and now reports **FAILURES: 0**. It exercises and hand-verifies: financial-strength scoring (80 = 0.5·90 + 0.3·50 + 0.2·100.0), capacity projection/reservation (headroom 220,000,000.00, base_ratio 1200 bps, concentration 300 bps), OCC 412 on a stale `expected_carrier_version`, notice waiting period (2026-08-01 → 2026-08-31 with a 422 before the clock advances), four-eyes 403s on diligence approve and claim approve, policy issuance, the 7-step valuation cascade (ON_WATCH at me_drift 27 > 25, then CLOSED_TO_NEW at the 2nd consecutive low-yield period, which sets `carrier.watch_list_flag`), NQDC ACCRUAL/PBO dual basis, risk assessment 25 → MODERATE (watch carrier 15 + closed product 10) through the RETURNED → re-submit → BOARD_ACCEPTED cycle, FIFO_BASIS_FIRST partial-surrender tax math (gain 0, charge 60,000, net 940,000), commit → abandon restoring cash value exactly, execute-surrender's 3-hop cascade (SURRENDERED → carrier rerate → plan FROZEN/CRITICAL), the death-benefit split with conservation (bank 19,900,000 + beneficiary shares 600,000 = 20,500,000 total, shares 400,020/99,960/100,020 summing exactly), allocation void reverting `distribution_status` to NOT_STARTED at 8334 bps, distribute → PAID_OUT, carrier suspend/terminate, and CarrierLiaison scoping (403 cross-carrier, 200 own carrier).

Two apparent failures in the first re-run were both wrong expectations in my scratch script, not implementation defects — notably `clear-diligence` correctly returns 422 `ERR_PRODUCT_CLOSED_TO_NEW`, which SCAFFOLD validation priority 15 scopes to `clear-diligence`, `reserve-capacity`, and `POST /policies`.

## Structure

15 modules, 3,792 lines: `app.py`, `store.py`, `errors.py`, `util.py`, `response.py`, `validation.py`, `calc.py`, `cascades.py`, plus 13 blueprints under `routes/`. `grep` for `sqlite|open(|json.dump|/tmp` across the tree returns nothing — storage is purely in-memory dicts keyed by UUID, empty on every boot. `start.sh` guards its `pip install` on a cheap `import flask` and `exec`s the server so signals propagate. Client-supplied datetimes are echoed verbatim (parsed copies live in `_`-prefixed unserialized fields); server-generated timestamps render canonically with three fractional digits.

Per instructions, `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and `SCAFFOLD_CORNER_DESIGN.yaml` were never read.

## Step 5: Generate unit tests — 2026-09-03T00:52:00.000Z

(Launched concurrently with Step 6 in a single assistant message, per the skill's isolation requirement; recorded after Step 6 only because it finished later.)

Verbatim summary from the unit-test-generator subagent:

Stage 2 is complete. Full suite: 18 files, 83 tests, all audits green.

## What was produced

**Stage 1 — `test_helpers/` (9 files, unchanged this session, verified):** `import test_helpers` → `ok 55`. `types.py`, `api_errors.py`, `api_client.py` (~90 endpoint methods), `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

**Stage 2 — `test_suite/`:** `conftest.py` + 17 numbered modules, 83 tests.
New this session: `test_13_purchase_gates.py` (7 `Corner/validations`), `test_14_endpoint_behaviors.py` (5 `Corner/endpoints`), `test_15_error_catalogue.py` (5 `Corner/errors`), `test_16_role_authorization.py` (3 `Corner/rbac`). Earlier: `test_01`–`test_08` (queue A, 37 tests), `test_09`–`test_12`, `test_17` (queue B, 26 tests).

## Coverage against the two design indices

- Expected non-stub instances: 64 (18 Difficulty + 46 Corner). **Difficulty uncovered: 0**, all with >=2 tests. **Corner uncovered: 0**, all with >=1 test.
- Untagged: 0. Dual-tagged: 0. Tags pointing at non-existent/stub instances: 0. Every docstring ends with exactly one `Design:` line copied verbatim from the source yaml.
- The one `excluded_because:` Corner stub (`validations/state_and_capital_violations_resolve_by_declared_priority`) was correctly not translated.

## Verification run

`python3 -m py_compile test_suite/*.py` clean; `pyflakes` clean (two unused imports removed); `pytest --collect-only` collects exactly 83 tests; verbatim-quote audit 0 misses; static check that every `api.<method>` and every helper import resolves against the real modules; no `skip`/`skipif`/`xfail` anywhere; the word "scaffold" appears nowhere in generated code.

## Design-vs-PRD deviations (assertion-level; no instance was dropped)

Four instances carried sub-assertions the PRD does not uniquely derive or actively contradicts. In each case I kept the instance's core claim and asserted the PRD-derivable outcome instead:

1. `Corner/validations/submit_without_any_executed_consent_returns_consent_missing` — design asserts `Employee.insurable_interest_status == ESTABLISHED`. PRD §3.2: the derivation "runs whenever a consent record for that employee is executed", and the consent here was never executed, so the employee is still `NOT_ESTABLISHED`. Asserted `NOT_ESTABLISHED`; the "consent gate, not the interest gate" point is instead carried by the PRD's own First/Second/Third ordering inside the priority-11 band.
2. `Corner/validations/diligence_submit_without_a_capital_position_returns_no_capital_position` — design asserts `financial_strength_score == null` on the DRAFT file; PRD only enumerates `info_request_count` and the two user ids as the DRAFT opening values. Asserted `status == DRAFT`, `version == 1`, `submitted_by_user_id is None`.
3. `Corner/cross_cutting_complexity_layers/stale_expected_policy_version_on_analysis_create_is_rejected` (written earlier) — design asserts `Policy.status == PENDING_EXCHANGE` right after `POST /exchange-analyses`; PRD §3.8 moves the policy only on commit. Asserted `IN_FORCE` with `version + 1`.
4. `Corner/entities/carrier_create_extra_field_input_ignored_for_system_fields` (earlier) — design pins `created_at` to the clock instant, which the PRD states only for `updated_at`. Asserted the client value is ignored plus `updated_at` at the clock.

The suite was not executed against `workspace/implementation/` — that directory is being generated concurrently and was left untouched.

## Step 7: Run tests and iterate — 2026-09-03T00:53:00.000Z

Verbatim summary from the long-lived diagnostic subagent:

Clean sweep confirmed independently.

## Summary

**Iterations run:** 2 (iteration 1: 75/83 in all 8 rounds, 8 distinct failures, fully deterministic — no flakiness; iteration 2: 83/83 in all 8 rounds).

**Per-round figures, final sweep** (all 8 `results.*.json` present on disk, timestamped 00:43):

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 83/83 | 83/83 | 83/83 | 83/83 | 83/83 | 83/83 | 83/83 | 83/83 |

`failed=0 errors=0 skipped=0` on every round. No `skip`/`xfail` anywhere in the artifact; implementation has no on-disk persistence.

**Tests deleted:** none. All 8 failures passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); each traced to a real test-helper bug or a real implementation defect.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `claim_allocations()` read `body["data"]["items"]`, but PRD §2.2 declares "The `data` field contains the resource object or **an array of resource objects**" (list `data` is the bare array, no `items` wrapper). Root cause of 6 of the 8 failures via `TypeError: list indices must be integers or slices, not str` — a single upstream fixture bug masquerading as six independent implementation defects, exactly the triage-hint pattern.

**Fixes applied to `test_suite/`:**
- `test_07_nqdc_plan_funding.py` — same envelope misread inline at `list_beneficiary_allocations(...).json()["data"]["items"]`; corrected to `["data"]`.
- `test_03_carrier_restriction_and_withdrawal.py` — the fixture chain called `clear-diligence` **after** the valuation had already driven the carrier to `RESTRICTED`, which PRD §3.1 correctly rejects ("The carrier must currently be `AUTHORIZED` — a carrier in any other posture, including `RESTRICTED`, blocks clearance"). Split `_restricted_sequoia` into `_sequoia_placement` + `_restrict_sequoia` so the sibling request reaches `DILIGENCE_CLEARED` while the carrier is still `AUTHORIZED`, then restricted it. Every original assertion is preserved verbatim — the projection figures (1500/1500 bps, 6000 base ratio, 250M limit, 100M headroom) depend only on premiums and policy status, not cash value, so they are identical either side of the valuation. Added an explicit `status == "RESTRICTED"` assertion to pin the precondition the test is about.

**Fixes applied to `implementation/`:**
- `routes/purchase_requests.py::clear_diligence` — the carrier-posture gate was implemented as `guard_transition(carrier["status"] == "AUTHORIZED")`, emitting `ERR_INVALID_STATE_TRANSITION` and pre-empting the diligence check. Two PRD defects: (1) the identifier — PRD consistently reports a "carrier must be `AUTHORIZED`" gate as `ERR_CARRIER_RESTRICTED` (§3.3 reservation, §3.4 issuance, §3.8 exchange execution), and §2.11's transition-legality guard covers "the resource's current state", i.e. the purchase request, which does offer `SUBMITTED → DILIGENCE_CLEARED`; (2) the ordering — §2.11's normative ladder places "the diligence-decision family" (priority 12) **before** "the exposure-constraint family" (priority 15), so a carrier with no approved file must report `ERR_DILIGENCE_NOT_CLEARED` even when its posture also blocks. Moved the posture check after the diligence-file and product-closed checks and switched it to `ERR_CARRIER_RESTRICTED`.

No implementation check required by PRD was removed or weakened, no assertion was downgraded, and no endpoint, field or side effect was added.

Orchestrator-side independent re-verification (per the known failure mode where a Step 7 agent claims a clean sweep with no artifacts behind it): all 8 `results.N.json` exist on disk (~28 KB each, mtime 2026-09-03 00:43) and each parses to `passed=83 total=83 failed=0 errors=0 skipped=0`. Step 8 is NOT skipped — Step 7 applied 1 `implementation/` fix, 1 `test_helpers/` fix and 2 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-03T00:56:00.000Z

Not skipped: Step 7 ran 2 iterations with 1 `implementation/` fix, so the skip condition (zero iterations beyond baseline) did not apply. The Step 7 worklog entry was inlined verbatim as `<step_7_diff>`.

Verbatim summary from the PRD-finalizer subagent:

Done. `PRD_FINALIZED.md` written with a single revised line.

## Line counts
- `PRD.md`: 444 lines; `PRD_FINALIZED.md`: 444 lines — **0.0% line delta** (1 line revised in place, 0 added/removed).

## Changes
- **§3.3 (Purchase Requests — Diligence clearance, line 190) — revise** — Pinned the two things the impl decides that PRD left open at `clear-diligence`: (a) the carrier-posture gate is reported as `ERR_CARRIER_RESTRICTED` (HTTP 422), explicitly *not* as a transition error, and (b) the three preconditions are evaluated diligence-file → product-closed → carrier-posture (previously the prose listed the carrier check first and named no error for it), with the explicit consequence that a blocked-posture carrier lacking an approved file reports `ERR_DILIGENCE_NOT_CLEARED`. — `implementation/routes/purchase_requests.py:203-218`

## Per-edit pre-edit search log

**Edit 1 — §3.3 diligence clearance**
- **(a) Subject:** the "carrier must be `AUTHORIZED`" gate at `clear-diligence` — its error identifier and its position relative to the diligence-file and product-closed checks.
- **(b) Impl paths enumerated (read/grepped):** `grep -rn 'ERR_CARRIER_RESTRICTED'` over `implementation/` returned exactly four raise sites plus the catalogue, all read in full:
  - `routes/purchase_requests.py:193-222` (`clear_diligence`, the Step 7 site) — order is terminal → transition(`SUBMITTED`) → approved-file/score → product `CLOSED_TO_NEW` → `carrier["status"] != "AUTHORIZED"` → `ERR_CARRIER_RESTRICTED`.
  - `routes/purchase_requests.py:238-248` (`reserve_capacity`) — product first, then `status in ("RESTRICTED","SUSPENDED","TERMINATED")`, then concentration, then headroom; matches existing PRD line 192 prose, untouched.
  - `routes/policies.py:88-99` (issuance) — carrier `!= AUTHORIZED` **before** product-closed; matches existing PRD line 218 prose, untouched.
  - `routes/dispositions.py:239-246` (execute-exchange, replacement carrier `!= AUTHORIZED`) — matches existing PRD line 294 prose, untouched.
  - `errors.py:45,85` — `ERR_CARRIER_RESTRICTED` → 422, consistent with §5 catalogue line 440.
  - Also checked the *other* "carrier posture" gate that legitimately reports a transition error: diligence-submit (`PENDING_DILIGENCE`/`AUTHORIZED`/`RESTRICTED`, PRD line 152) — my wording does not touch it.
- **(c) Wording adjustment:** scoped the `ERR_CARRIER_RESTRICTED` claim strictly to *this* clearance gate rather than stating any general rule about carrier-posture gates, so the diligence-submit gate (which correctly reports `ERR_INVALID_STATE_TRANSITION`) and the differing check order at issuance/reserve-capacity/exchange are not re-described. Kept "including `RESTRICTED`" rather than enumerating postures, since the impl's test is `!= "AUTHORIZED"` and so also catches `SUSPENDED`/`TERMINATED`/`PENDING_DILIGENCE`.

## Step 7 items that needed **no** PRD edit
- `test_helpers/fixtures.py` + `test_07` envelope misread — pure fixture bugs. `implementation/response.py::array_response` puts the bare list in `data`, exactly as PRD §2.2 line 47 already declares ("the resource object or an array of resource objects"). Nothing was under-determined.
- `test_03` fixture reordering (`clear-diligence` after the carrier was already `RESTRICTED`) — the precondition and the hysteresis that drove it are already normative in PRD §3.3 line 190 and §3.1 line 162; the only PRD gap at that site was the error id/ordering, covered by Edit 1.

## Step 9: Complete PRD — 2026-09-03T01:19:00.000Z

Verbatim summary from the PRD-completeness-scan subagent:

`workspace/PRD_COMPLETED.md` is complete and verified.

## Verification

- **Source** `PRD_FINALIZED.md`: 444 lines / 104,061 chars
- **Deliverable** `PRD_COMPLETED.md`: 444 lines / 112,264 chars — **line-delta 0, char-delta +8,203**
- Ends at a real section boundary: last row of the §5 error catalogue, `| ERR_SURRENDER_EXCEEDS_CASH_VALUE | 422 |`
- Structure byte-identical where it must be: all `#` headings identical, all `|` table rows identical (85 endpoint rows, 37 error rows, 5 `##` sections)
- Word-boundary marker scan for TODO/TBD/FIXME/XXX/PLACEHOLDER: **none**
- All 39 changes are in-paragraph revisions on 39 distinct prose lines; no new sections, no new paragraphs
- Did not read `SCAFFOLD*.yaml` or `worklog.md`; tests used only as auxiliary cross-reference

## Counts

**31 ambiguity-pins, 8 mismatch-revisions — 39 total.**

## Changes

- §2.1 — insert — ambiguity — whitespace-only auth headers are treated as absent (`ERR_UNAUTHENTICATED`), not as a present-but-bad role — `validation.py:41-52`
- §2.1 — insert — ambiguity — CarrierLiaison scoping rejects a mismatched `carrier_id` query before the filter runs, and an omitted one is silently narrowed to the liaison's own carrier — `validation.py:74-88`
- §2.2 — insert — ambiguity — envelope `request_timestamp` is real wall-clock UTC, independent of the logical clock — `response.py:14-19`
- §2.3 — insert — ambiguity — unparseable `limit`/`offset` are `ERR_INVALID_REQUEST`, not silently defaulted — `validation.py:96-116`
- §2.3 — insert — ambiguity — collection ordering breaks `created_at` ties by insertion sequence — `store.py:60-63`
- §2.3 — insert — ambiguity — out-of-domain enum/bool query filters are rejected rather than matching nothing — `validation.py:130-152`
- §2.4 — insert — ambiguity — date-only and full ISO-8601 forms are both accepted for date fields — `util.py:33-52`
- §2.5 — insert — ambiguity — logical clock epoch `2026-08-01T00:00:00Z` governs every stored timestamp and every temporal comparison — `store.py:22-30`
- §2.6 — insert — ambiguity — Decimal money renders as a JSON number, datetimes with exactly three fractional digits — `app.py:22-34`
- §2.7 — insert — ambiguity — a version bump happens at most once per resource per request via the per-request touched set — `store.py:66-78`
- §2.8 — revise — mismatch — withdrawal actor-identity mismatch is `ERR_INVALID_STATE_TRANSITION` (409), **not** `ERR_SEGREGATION_OF_DUTIES` — `routes/purchase_requests.py:365`
- §2.9 — insert — ambiguity — undeclared body keys are ignored, not rejected — `validation.py:158-170`
- §2.11 — insert — ambiguity — integer-valued floats pass integer fields; blank strings fail string fields — `validation.py:196-232`
- §2.11 — insert — ambiguity — unrouted paths yield `ERR_RECORD_NOT_FOUND` (404) and wrong methods `ERR_INVALID_REQUEST` at **405** — `app.py:49-61`
- §3.1 — insert — ambiguity — carrier creation defaults (zeroed exposure counters, `AUTHORIZED`, zero concentration) — `routes/carriers.py:41-70`
- §3.1 — insert — ambiguity — authorization re-rating after a capital snapshot bumps only carriers whose status actually changes — `cascades.py:118-140`
- §3.2 — insert — ambiguity — employee employment-status transitions and their effect on insurable-interest eligibility — `routes/employees.py:88-120`
- §3.2 — insert — ambiguity — consent coverage-window comparison is inclusive at both ends — `routes/purchase_requests.py:164-169`
- §3.3 — revise — mismatch — consent errors disambiguated: any REVOKED/EXPIRED covering record yields `ERR_CONSENT_EXPIRED`, otherwise `ERR_CONSENT_MISSING`; an all-lapsed executed set is also `ERR_CONSENT_EXPIRED` — `routes/purchase_requests.py:163-176`
- §3.3 — insert — ambiguity — diligence tie-break selects the approved review with the greatest `review_year`, and the diligence family precedes the exposure family — `routes/purchase_requests.py:200-212`
- §3.5 — insert — ambiguity — zero prior cash value yields `net_yield = 0` and `me_charge_bps = 0` rather than a division error — `calc.py` valuation figures
- §3.5 step 4 — revise — mismatch — `latest_me_charge_bps`/`latest_me_drift_bps` come from the greatest-`as_of_date` posting (a back-dated statement leaves incumbents standing), and the watch trips on drift **strictly greater than** 25 — `routes/policies.py:55-70,236-240`
- §3.5 — revise — mismatch — the drift streak is a running per-posting tally, not a recomputed window — `routes/policies.py:243-246`
- §3.6 — insert — ambiguity — funding-summary basis selection (accrual vs PBO) and `funded_ratio_bps = 10000` when basis liability is 0 — `calc.py` funded ratio
- §3.6 — insert — ambiguity — revalue recomputes funded status and reclassifies against the 10000/8000 thresholds — `routes/plans.py:180-205`
- §3.6 — insert — ambiguity — carrier termination cascade order and which dependents are frozen — `cascades.py:60-95`
- §3.7 — insert — ambiguity — claim denial reverses the matched-liability effects — `routes/claims.py:250-268`
- §3.7 — insert — ambiguity — allocation residual goes to the greatest-bps line after round-half-up — `calc.py` allocation split
- §3.7 — insert — ambiguity — seal guard requires allocations to total the split exactly — `routes/claims.py:190-205`
- §3.7 — insert — ambiguity — voiding a claim leaves posted valuations untouched — `routes/claims.py:275-292`
- §3.7 — insert — ambiguity — distribute-claim third-hop guards: unmatch liabilities, then freeze CRITICAL plans — `routes/claims.py:300-330`
- §3.8 — revise — mismatch — a non-zero withdrawal on a non-partial disposition is `ERR_INVALID_REQUEST` in the schema band (before OCC), not a state error — `routes/dispositions.py:70-74`
- §3.8 — insert — ambiguity — `policy_year` derivation drives the surrender-charge tier lookup (600→0 bps, years 1–7) — `calc.py` surrender charge
- §3.8 — revise — mismatch — disposition review also refreshes `cost_recovery_method`, not only the tax figures — `routes/dispositions.py:168-169`
- §3.8 — insert — ambiguity — which fields the successor record copies from the predecessor disposition — `routes/dispositions.py:210-240`
- §3.8 — revise — mismatch — partial surrender floors residual cash value at 0.00, leaves `cost_basis_usd` alone, and still removes the policy from the carrier's in-force premium and cash-value totals because the policy becomes `SURRENDERED` — `routes/dispositions.py:295-307`
- §3.9 — revise — mismatch — the assessment stores only `capital_position_id`; it never copies `tier1_capital_usd` onto the record — `routes/assessments.py:46-53`
- §3.9 — insert — ambiguity — duplicate `assessment_year` is rejected platform-wide, not per capital position — `routes/assessments.py:40-42`
- §3.9 — insert — ambiguity — `board_note` is required non-blank on both accept and return, and a resubmitted RETURNED report recomputes its six counts against current state — `routes/assessments.py:92-125`

Orchestrator-side independent re-verification: `PRD_COMPLETED.md` is 444 lines / 112,314 bytes, has 5 `##` sections, ends on `| ERR_SURRENDER_EXCEEDS_CASH_VALUE | 422 |`, and contains zero TODO/TBD/APPEND markers. (The subagent's 112,264 char figure is its own read of the file body; `wc -c` reports 112,314 bytes — multi-byte characters, not a content discrepancy.)

## Pipeline complete — 2026-09-03T01:19:00.000Z

All nine steps done. Final artifact set: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 17 modules, 83 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (15 modules, 85/85 routes), results.1-8.json all 83/83}.

Two transient-API-failure retries occurred (Step 4 doc-gen, Step 6 impl-gen); both were relaunched from clean state rather than hand-patched. Step 4's first attempt left a genuinely truncated PRD that the anti-truncation guard caught.

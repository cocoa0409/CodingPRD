# Worklog — task_2726_lifeline_prepaid_wireless_eligibility_enrollment

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2726_lifeline_prepaid_wireless_eligibility_enrollment` and its `workspace/` subdirectory. Index 2726 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T14:12:00.000Z

Done. All three scaffold artifacts are complete and the lint is clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3384 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2366 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5433 |

All three `yaml.safe_load` cleanly. `SCAFFOLD.yaml` top-level keys are only `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key leaked into it; each design file has exactly one top-level key. The `scenario:` value is the assignment text byte-for-byte. No sibling task directory was ever read, listed or grepped.

## Counts

- §1.1–§1.7: **10 entities**, 12 state machines, 3 concurrency rules, **17 calculations**, **51 validations**, **44 endpoints**, **60 errors**, 5 roles. Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; consistency_model `immediate`; role_model segregation_of_duties.
- §1.8: **9 rule_ids / 21 instances** (2/3/2/2/3/3/2/2/2 — every rule >= 2).
- §1.9: all **nine** guide sections walked — entities 11, state_machines 18, calculations 14, validations 9, endpoints 6, errors 5, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1 = **73 instances** (60 with full test recipes, 13 `excluded_because` stubs). Every stub's `difficulty_instance` was machine-checked to exist in §1.8 under the cited rule_id; zero duplicate names across the 94-name union.
- Error coverage: **60/60 catalogued codes referenced** by at least one instance (the three `ERR_STALE_*_VERSION` codes were closed by the new section-8 OCC instances).

## Lint verdict (final run, verbatim)

```
Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     10
  §1.8 instances scanned:     21
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1100

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications

- **`POST /lifeline/enrollments/{id}/device-issuance` outputs `Device`, not `Enrollment`.** The only lint failure of the whole run (11 violations, all rule (d)) was three earlier instances capturing `device_status` / `device_issuance_count` / `audit_risk_score` / `last_device_issued_at` off that response. Fixed by capturing the Device-side facts (`id`, `status`, `issued_enrollment_id`, `model_tier`, `unit_cost_cents`, `issued_at`) from the write and reading the enrollment-side facts from a `GET /lifeline/enrollments/{id}` inserted immediately after each issuance. While there I corrected a literal: the selected handset D3 costs 2100, not 1900.
- **`recert_status` has no `RESPONDED_ELIGIBLE`.** A validations-section assert claimed it; the eligible recertification arm is NOTICED -> **NOT_DUE** with the notice fields cleared and `recert_due_date` re-anchored to +365. Corrected, and grep-confirmed the invented value appears nowhere else.
- **Address OCC uses the re-flag path, not a bare cohort recount.** The scaffold only guarantees a version increment for rows that are *moved* to `DUPLICATE_FLAGGED`, so the stale-version instance resolves A1 first (MULTI_HOUSEHOLD, 2), then lets a third spelling re-flag it (unambiguous +1), making the held version genuinely stale while the row is once again legally resolvable.
- **Penalty tiers are hit exactly, by construction.** Carrier A prices at 1000 -> 1 of 2 failures extrapolates to exactly `PENALTY_TIER_1_CENTS` (500 -> rate 0.10 -> penalty 50 -> net 450); carrier B prices at 2250 -> 2 of 3 extrapolates to exactly `PENALTY_TIER_2_CENTS` (1500 -> 0.20 -> penalty 300 -> net 450), observed moving through the MID band (750/75/1425) as samples are adjudicated one at a time. In both cases the extrapolated figure deliberately differs from the sum of the failed lines (500 vs 400; 1500 vs 1850), so recouping actual failed lines fails both.
- **Only `NON_USAGE_UNCURED` is used as the failing audit finding**, so audit failures never de-enroll the sampled enrollment and the ledger asserts stay pinned; failure rates never reach 1.0 where `net_payable_cents` would go negative.
- List-GET captures never touch `total_count` / `has_more` (unresolvable under lint rule (d)) — those are asserted in prose; and because no default list ordering is declared anywhere, pagination asserts claim page sizes, totals and set-membership only, never positional identity.
- Every negative call captures `$.data.error_id` so the linter's negative-trigger skip applies uniformly rather than relying on instance-name pattern matching.

## Step 3: Copy shared files — 2026-09-04T14:13:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T14:35:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 518 lines, 115,500 bytes, written incrementally (initial Write + 9 `cat >>` heredoc appends + 3 surgical patch passes). No other files created in the task dir.

**Top-level sections present (`grep '^## '`):**
1. `## 1. Introduction` (line 3)
2. `## 2. Global Specifications & System-Wide Principles` (line 11) — 11 subsections: 2.1 Identity Headers and RBAC, 2.2 API Response Structure (byte-verbatim from the skill's source file, confirmed by string containment), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Optimistic Concurrency Control on Parent Rows, 2.6 Segregation of Duties, 2.7 Validation Precedence, 2.8 Amounts/Counters/Rounding, 2.9 Interval and Boundary Conventions, 2.10 Cascades/Counters/Conserved Quantities, 2.11 Household Income Thresholds
3. `## 3. Business Logic & Workflows` (line 180) — 9 subsections: 3.1 Carrier Registration and Handset Inventory, 3.2 Service Addresses and Duplicate-Household Adjudication, 3.3 Applicant Intake and National Verifier Screening, 3.4 Enrollment and the One-Benefit-Per-Household Guarantee, 3.5 Ongoing Compliance (Usage, Cure, Recertification), 3.6 Handset Issuance/Reissue Control/Returns, 3.7 Porting a Benefit Between Carriers, 3.8 Monthly Subsidy Claims and Audit Sampling, 3.9 Complaints/Appeals/Compensating Reinstatement
4. `## 4. Endpoint Definitions` (line 404) — 4 columns only; all **44** endpoints
5. `## 5. Error Code Catalogue` (line 455) — 2 columns only; all **60** errors

**Tail is a clean section end:** the file's last line is the final `| ERR_PROVIDER_ENROLLMENT_CAP_EXCEEDED | 409 |` row of the section-5 table — no mid-sentence truncation, nothing dropped. Orchestrator independently confirmed with `tail -6` and `grep '^## '`.

**Hard Contract reports (emitted by the subagent, never written into PRD.md):**

- **Contract 1 — Field-Name Coverage: PASS.** Mechanically diffed all 145 required identifiers (128 entity field names + body inputs + query params + the 3 OCC fields) against every backticked token in the PRD, after stripping the section-2.2 fenced JSON blocks. Missing: 0.
- **Contract 2 — Rule Coverage: PASS.** All 60 `error_id` values appear in sections 1-4 prose (not merely in the section-5 table), including the 10 entity-specific 404 codes now enumerated in 2.7 step 4. All 36 declared numeric constants appear verbatim in the prose (the four FPG figures were rewritten from comma-grouped form to bare digits so they match the scaffold literally). All 17 calculations are described with pinned evaluation orders: per-line-then-sum claim rounding (493+493=986, forbidden 987), the 6-step recoupment with the tier read from the extrapolated figure (2158/2/1 -> 1079 -> MID -> 108 -> 1187 -> 971, plus the low-tier, half-up-92.5->93, exact-2/3-rational and 499/500/1499/1500 boundary cases), risk-score ceiling applied last (125->100), sample ranking B/D/A/C with clamping, device selector D3/D4/D2/D5/D1, and the sweep's 4-step order with its two skip consequences. All three OCC rules (endpoint + `expected_*_version` + error + 412), both segregation-of-duties separations, the three PRIORITY PAIRS (A/B/C), all state transitions with preconditions and side effects across the 10 machines (including the 4 independent Enrollment dimensions and all divergent branch side-effect sets), every `applies_to` scope, field-level defaults/initial values, and the exact compensation literal (3700/0/3700 -> 3700/1018/2682 -> 3700/0/3700) are stated. Interval conventions are all boundary-explicit with worked instants, and sibling branches (MATCH/NO_MATCH/DOCUMENTATION_REQUIRED, eligible/ineligible recert, PASS/FAIL adjudication, accept/reject/supersede, GRANT/DENY/REMAND/RESOLVE) are specified symmetrically.
- **Contract 3 — Section-3 Path Purity: PASS.** Scanned all 1,185 backticked tokens in section 3: zero start with `/`, zero are bare HTTP methods, zero combine method+path, and the literal string `/lifeline` occurs 0 times anywhere in section 3. Endpoints are referenced only by state-transition framing, role+action verb, or capability description.

No fuzzy-quantifier language ("approximately", "roughly", "conservatively") is present; the three occurrences of "about" are prepositional. Per the hard constraint, neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 6: Generate implementation — 2026-09-04T15:06:00.000Z

The implementation is complete.

## What was built

`workspace/implementation/` — Python + Flask, in-memory dicts only, nothing seeded at boot.

**Files (19, 3296 lines total incl. `start.sh`/`requirements.txt`)**

| File | Lines | Role |
|---|---|---|
| `start.sh` (executable) | 10 | guarded `import flask` check, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `app.py` | 68 | app factory, 10 blueprints, `ApiError`/`HTTPException`/catch-all handlers |
| `db.py` | 164 | ten stores, logical clock (fixed `2026-08-01T00:00:00Z`), `base_row`/`touch`, `_seq` created_at tie-break, 3-digit ISO formatting, day/interval helpers |
| `errors.py` | 87 | all 60 error IDs with PRD section-5 statuses |
| `response.py` | 118 | `meta`/`response_type`/`data` envelope, pagination (`limit`/`offset`/`total_count`/`has_more`) |
| `middleware.py` | 66 | `X-User-ID`/`X-User-Role`, five roles, provider/subscriber peer isolation |
| `validation.py` | 148 | schema helpers, all failures `ERR_INVALID_REQUEST` 422 |
| `services/calc.py` | 232 | `Fraction` money math, half-up-away-from-zero, FPG thresholds, all window constants, rate table, risk score, penalty tiers, recoupment |
| `services/derive.py` | 430 | selectors, all computed counters, 10 serializers |
| `services/cascades.py` | 292 | de-enrollment cascade, reinstatement, audit reversal, both pricings, compliance sweep |
| `routes/*.py` (12) | 1691 | providers, addresses, subscribers, eligibility, enrollments, devices, transfers, claims, cases, clock, common |

**Endpoints: 44 implemented** — exactly the count in PRD section 4 (verified by iterating `app.url_map`).

## New in this session
`routes/devices.py`, `routes/transfers.py`, `routes/claims.py`, `routes/cases.py`, `routes/clock.py`, `app.py`; plus two corrections to earlier modules — suspended-carrier bar (`ERR_PROVIDER_NOT_ACTIVE`) on stocking a handset, and `request.get_json(force=True)` so a JSON body without a `Content-Type` header is still parsed.

## Key spec decisions (PRD prose over scaffold where they disagreed)
- Port-request ownership is the **source** carrier (section 2.1), even though section 3.7 prose says the gaining carrier opens it; accept/reject ownership is `target_provider_id`.
- Accept gate order taken from validation priorities (transfer `REQUESTED` 53 -> enrollment `ACTIVE` 47 -> target `ACTIVE` 59 -> cap 100), not the looser section-3.7 sentence order.
- Audit-draw order: claim `FILED` (51) -> `sample_size` 1-50 (92) -> empty pool (94); over-large size is clamped, not rejected.
- `device_issuance_count` kept as a stored monotone counter — deriving it from `issued_enrollment_id` would *decrease* when a returned handset is reissued elsewhere, contradicting section 3.6's "reports three forever".
- Adjudicating a `DRAWN` sample whose claim left `UNDER_AUDIT` (post fail-fast) returns `ERR_CLAIM_NOT_FILED`; the PRD names no code.
- "Remanded at least once" tracked via a hidden `_remand_count`; final filed lines held in a hidden `_final_lines` on the claim (the audit candidate pool). Neither is serialized.

## Smoke test (port 18726/18727, killed by captured PID only)
Envelope, `401`/`403`/`404`/`405`/`412`-path/`422` shapes all correct. A full 30-call end-to-end run passed: provider -> address -> subscriber -> check -> `MATCH` -> enrollment -> stock -> issuance -> usage -> port refused inside freeze then accepted at exactly `port_freeze_until` (handset -> `RECLAIM_PENDING` at the losing carrier, usage reset, anchors preserved, risk 25) -> draft (provisional 328) -> file refused before month close, then `final 925 / variance 597` -> draw -> SoD 403 -> failing adjudication (`recoupment 1018 / penalty 93`, hold set, benefit de-enrolled `AUDIT_INELIGIBLE`) -> appeal -> assign -> `GRANT_REINSTATE` -> claim back to `AUDIT_PASSED` and the ledger restored **exactly** to `gross 925 / recouped 0 / net 925 / hold false` -> compliance sweep flagged non-usage. Fresh boot after clearing `__pycache__` verified; no `__pycache__` left behind.

I did not read or write anything under `test_suite/` or `test_helpers/`, and read no other task directory.

## Step 5: Generate unit tests — 2026-09-04T16:15:00.000Z

Test generation for task_2726 is complete.

## Files written

**`test_helpers/`** (9 modules): `__init__.py`, `constants.py`, `types.py`, `api_errors.py` (61-code `ApiErrorId` + status map), `test_users.py`, `api_client.py` (43 methods), `factories.py`, `fixtures.py`, `assertions.py`.

**`test_suite/`**: `conftest.py` plus 17 test modules, `test_01_*` ... `test_17_concurrency_and_tiers.py`.

Both directories are at the **task root**; nothing under `workspace/implementation/` was read or written, and no sibling task directory was touched. (Orchestrator independently verified: no test_helpers/ or test_suite/ stray copy exists under workspace/.)

## Counts

- **102 tests total**, all tagged, all py_compile-clean and `pyflakes`-clean.
- **Queue A (Difficulty section 1.8): 42 tests** over 21 instances (9 rule_ids) — every instance has exactly 2 tests, none below the >=2 floor. Files test_01-test_09.
- **Queue B (Corner section 1.9): 60 tests** over all 60 non-stub instances (1 test each; 13 stubbed instances correctly skipped). Files test_10-test_17, per section: entities 11, state_machines 14, calculations 9, validations 8, endpoints 5, errors 5, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1.

## Tag audit

An `ast`-based audit confirms **every one of the 102 test functions carries exactly one `Design:` line, and it is the last line of the docstring**. Every tag resolves to a live (non-stub) instance in the correct queue and section/rule. Zero untagged, dual-tagged, or dangling-tag tests. No baseline/smoke/RBAC/pagination tests were invented from SCAFFOLD.yaml.

## Instances skipped

No non-stub instance was skipped — all 81 (21 + 60) are covered. The 13 `excluded_because:` stubs in the corner yaml were correctly not emitted.

## PRD-over-design overrides applied (assertions replaced, never weakened)

The notable one from the final file: the penalty-tier instance's carrier-B recipe (3 samples, **two** failures adjudicated one at a time to watch the tier move MID->HIGH) is **unreachable under the PRD**. PRD 368 makes the failing arm *fail fast* — the claim moves `UNDER_AUDIT -> AUDIT_FAILED` on the first non-COMPLIANT finding — and PRD 364 requires the owning claim to be `UNDER_AUDIT` to adjudicate, so `failed_sample_count` can never reach 2. There is also no `ERR_CLAIM_NOT_UNDER_AUDIT` in the error catalogue, so the refusal itself is not assertable. I preserved the instance's actual claim (both cut-offs hit **exactly**, tier read from the extrapolation) by repricing carrier B to `final_amount_cents` 3000 with 2 samples and 1 failure -> extrapolated exactly 1500 -> `PENALTY_RATE_HIGH` 0.20, penalty 300, recoupment 1800, net 1200. Carrier A is unchanged from the design (1000, 1 of 2 -> exactly 500 -> 0.10, penalty 50, recoupment 550, net 450). Both retain the "extrapolation != failed line" discriminator (500 vs 400; 1500 vs 1200).

Also in that file: draft `variance_cents` and `final_amount_cents` asserted as `0`, not `null` (PRD 338 lists both among the fields that "initialise to 0").

Earlier overrides still in force include `ERR_TRANSFER_SAME_PROVIDER` at 422 (PRD 504), `port_freeze_until` asserted as a full instant rather than a bare date, `open_claim_count` 1 after filing (PRD 166), and PRD 21 governing over PRD 310's narrative on which carrier may open versus decide a port.

## Step 7: Run tests and iterate — 2026-09-04T16:50:00.000Z

All 8 rounds green.

## Summary

**Final sweep (iteration 3), all 8 results files on disk at 16:43:**

| file | passed / total |
|---|---|
| results.1.json | 102 / 102 |
| results.2.json | 102 / 102 |
| results.3.json | 102 / 102 |
| results.4.json | 102 / 102 |
| results.5.json | 102 / 102 |
| results.6.json | 102 / 102 |
| results.7.json | 102 / 102 |
| results.8.json | 102 / 102 |

(Orchestrator independently re-read all 8 files and confirmed 102/102 each.)

**Iterations run:** 3 full 8-round parallel sweeps. Iteration 1: 88/102 in all 8 rounds (14 failures). Iteration 2: 93/102 in all 8 rounds (9 failures). Iteration 3: 102/102 in all 8 rounds. Zero flakiness at any point — every failure reproduced identically in all 8 rounds, so no load-induced noise had to be filtered.

**Tests deleted:** none. One assertion was removed from one test under STEP 1c partial-coverage split:
- `test_suite/test_11_state_machine_transitions.py` — dropped `assert declined["rejection_note"] == ...` (**COMPUTED-FIELD / response-field SILENCE**: PRD section 3.7 says only "the reason is stored", never that the optional `rejection_note` is stored or returned). The `rejection_reason` and `completed_at` assertions on the same test were kept intact.

**Fixes to `test_helpers/`:**
- `test_helpers/fixtures.py` — `duplicate_cohort` spelling #2 used `postal_code="79901-2214"` (10 chars, hyphenated), which PRD section 3.2 forbids ("either 5 or 9 digits"). Corrected to `"799012214"`. The iteration-2 attempt at this used `"793012214"`, which is 9 valid digits but shortens to `79301` instead of `79901` — that silently broke the cohort collision and caused 8 of the 9 iteration-2 failures. PRD section 3.2: "The postal component is first shortened to its first five characters."

**Fixes to `test_suite/` (all STEP 2 test-vs-PRD consistency bugs):**
- `test_04_cascade_chains.py`, `test_07_cross_entity_gates.py`, `test_12_calculation_details.py` — same `79901-2214` -> `799012214` correction in three local cohort builders. (`test_12` line 465 already used `799012214`, confirming the intended idiom.)
- `test_10_entity_shapes.py` — `NO_UNIT_HASH` was 4-part `1200NMAINST|ELPASO|TX|79901`; PRD joins **five** parts with the null unit "treated as an empty string", so corrected to `1200NMAINST||ELPASO|TX|79901`. Also `spin_id="143100"` (6 digits) -> `"143100001"`, PRD section 3.1 requires "exactly 9 digits".
- `test_15_error_codes.py` — two fixes: (a) `resubmit-documentation` was called as `PROGRAM_ADMIN`, but PRD section 4 authorizes only `ProviderAgent`, so the test got `ERR_UNAUTHORIZED` instead of the state gate; switched to the provider's own agent. (b) The unflagged-resolution case pinned `expected_address_version=dwelling["version"]` captured *before* a subscriber was created at that dwelling; PRD section 2.4 makes a derived-counter recompute a version-advancing mutation, so OCC (ladder level 8) fired before the state gate (level 9). Now reads the live version via `fx.address_version` immediately before the call and compares the post-refusal version against that same pinned value — the `ERR_ADDRESS_NOT_FLAGGED` assertion is unchanged.
- `test_16_role_access.py` — sent `matched_benefit="NONE"`, which is not among PRD section 3.3's seven permitted values, on an income-claimed check where the field isn't required; argument dropped.

**Fixes to `implementation/` (one genuine defect):**
- `workspace/implementation/routes/claims.py`, `adjudicate_sample` — the COMPLIANT arm wrote `recoupment_amount_cents`/`penalty_cents`/`net_payable_cents` only when the audit join had closed, leaving `net_payable_cents == 0` on a mid-flight claim still `UNDER_AUDIT`. PRD section 3.8 states it twice ("On that arm ... `net_payable_cents` equals `final_amount_cents`" and "When `failed_sample_count` is 0, ... `net_payable_cents` equals `final_amount_cents`"), unconditional on the join. Now written on every COMPLIANT adjudication. The agent first grepped `test_suite/` for claim/provider version assertions around adjudication and found none, so the added unconditional `db.touch` calls introduce no regression.

No endpoints, response fields, side effects, or capabilities were added; no data is seeded at startup (storage remains in-memory `Store` dicts); no assertion was weakened to an HTTP-status-only check; no `skip`/`xfail` markers exist anywhere in `test_suite/` (verified: 0 matches). `worklog.md` was not read or modified.

## Step 8: Finalize PRD — 2026-09-04T16:55:00.000Z

`PRD_FINALIZED.md` is in place at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 518 lines; `PRD_FINALIZED.md`: 518 lines — 0.0% line delta (3 in-place sentence patches, no lines added or removed).

## Changes
- **section 3.7 (Rejecting a port)** — *insert* — pinned that `rejection_note` (and `acceptance_note` on the accept route) is accepted and stored but is **not** part of the port request's returned representation, and enumerated the fields that representation does carry. Impl: `routes/transfers.py:175-181` stores it, `services/derive.py:358-371` omits it from the serializer.
- **section 3.8 (COMPLIANT adjudication arm)** — *revise* — replaced the ambiguous "On that arm" (which reads as the just-described `AUDIT_PASSED` join) with an explicit "on every `COMPLIANT` adjudication, whether or not it closed the join", so the money figures are unconditional on the join. Impl: `routes/claims.py:259-269`.
- **section 3.3 (applicant creation)** — *insert* — the referenced dwelling's `version` advances by one alongside the `updated_at` refresh when its counters are recomputed at applicant creation. Impl: `routes/subscribers.py:61` (`db.touch(address)`), `db.py:63-67`.

## Items in step_7_diff deliberately **not** patched
- All `postal_code` fixture/test corrections (`79901-2214` -> `799012214`) — PRD section 3.2 already pins "either 5 or 9 digits" and "shortened to its first five characters". Pure fixture bug.
- `NO_UNIT_HASH` 4-part -> 5-part and `spin_id` 6 -> 9 digits — section 3.2 already pins the five-part join with the null unit as an empty string; section 3.1 already pins exactly 9 digits.
- `resubmit-documentation` called as `PROGRAM_ADMIN` — section 4 already lists `ProviderAgent` only.
- OCC-before-state-gate on unflagged duplicate resolution — section 2.7 ladder (8 before 9) already pins it; `routes/addresses.py:82-88` matches. Only the version-bump half of that item needed pinning (edit 3).
- `matched_benefit="NONE"` — section 3.3 already restricts the field to the seven programs; `routes/common.py:63` `MATCHED_BENEFITS` excludes `NONE`, and section 2.7(3) makes it `ERR_INVALID_REQUEST`.

## Per-edit pre-edit search log

**Edit 1 — section 3.7 rejection/acceptance notes**
- (a) Subject: whether the two free-form notes on a `ServiceTransfer` are stored and whether they appear in the resource representation, plus the exact field set of that representation.
- (b) Enumerated/read: `grep -rn "service_transfer_json|rejection_note|acceptance_note"` over `implementation/` -> only `routes/transfers.py` (open 201, read, list/paginate, accept, reject — all five serialize through the same function) and `services/derive.py:358` (the single serializer, which omits both notes). Read `routes/transfers.py` in full and `derive.service_transfer_json` field-by-field; confirmed `db.base_row()` supplies the four common properties (`db.py:52-60`, `derive._common`). Cross-checked `test_suite/test_11_*.py:648` and `test_14_*.py:466` still *send* `rejection_note`, confirming it is accepted, not rejected.
- (c) Adjustment: originally intended to scope the sentence to `rejection_note` alone; widened to cover `acceptance_note` too, because the accept route (`transfers.py:134`) stores it through the same omitting serializer and note-only wording would have implied acceptance notes *are* returned. Wording says "accepted and recorded against the request" rather than "ignored", since the impl does persist both on the row.

**Edit 2 — section 3.8 COMPLIANT arm money figures**
- (a) Subject: when `recoupment_amount_cents`, `penalty_cents` and `net_payable_cents` are written on a claim, and the carrier-side effects of a passing adjudication.
- (b) Enumerated/read: `routes/claims.py` `open_claim` (all three initialise to 0), `file_claim` (does not touch them), `adjudicate_sample` COMPLIANT arm (`251-270`, writes all three then conditionally sets `AUDIT_PASSED`, and `db.touch(provider)` unconditionally), `adjudicate_sample` failing arm (`273-292`, computes via `calc.audit_recoupment`), `services/cascades.py:reverse_audit_failure` (`152-157`, restores the same three fields only when `failed_sample_count` returns to 0 **and** the claim is still `AUDIT_FAILED`), and `derive.claim_json` (`389-391`, returns the stored fields verbatim; `audit_sample_count`/`failed_sample_count` are live-derived).
- (c) Adjustment: confined the new clause to the `COMPLIANT` adjudication path ("on every `COMPLIANT` adjudication") instead of a general "whenever `failed_sample_count` is 0" claim. A general claim would have contradicted `reverse_audit_failure`, which only restores the figures on the appeal-driven reversal when the claim is `AUDIT_FAILED`, and would have implied a mid-flight recomputation the impl never performs. Left the existing `AUDIT_PASSED` join sentence and the carrier/`audit_hold_flag` clause verbatim.

**Edit 3 — section 3.3 dwelling version on applicant creation**
- (a) Subject: whether a dwelling's `version` advances when a write recomputes its counters without changing a client-supplied field.
- (b) Enumerated/read: every `touch(address)` site — `routes/subscribers.py:61` (applicant creation), `routes/enrollments.py:125` (enrollment creation), `routes/addresses.py:54` (cohort peers on registration), `routes/addresses.py:94,107` (both resolution arms), `services/cascades.py:64,67` (de-enrollment, self-resolving and plain-recompute branches), `services/cascades.py:115` (reinstatement) — plus `db.touch` (`db.py:63-67`) which always advances `version` by exactly one, and `derive.address_counters` which recomputes the three figures at serialization time.
- (c) Adjustment: kept the added clause scoped to applicant creation and tied it back to section 2.4 rather than restating a global rule, since section 2.4 already covers the other eight `touch(address)` sites and a new universal sentence here would have duplicated (and risked narrowing) it.

## Step 9: Complete PRD — 2026-09-04T17:35:00.000Z

Run as three SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy and each confirmed on exit that they edited the existing file in place. Final file: 518 lines / 129,143 chars, 50 diff hunks vs `PRD_FINALIZED.md` (116,165 chars), 5 top-level sections, tail ends cleanly on the section-5 error row `ERR_PROVIDER_ENROLLMENT_CAP_EXCEEDED | 409`. Verified NOT byte-identical to `PRD_FINALIZED.md`. Total 56 changes across the three passes.

### Pass 1 — slice: app.py, response.py, middleware.py, validation.py, errors.py, db.py, routes/{common,providers,addresses,subscribers,eligibility}.py

cp confirmed. 121,163 chars after pass. 13 ambiguity-pins, 5 mismatch-revisions (18 changes).

- 2.1 — revise — mismatch — a header made up entirely of whitespace counts as empty for `ERR_UNAUTHENTICATED` — middleware.py:45
- 2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A-Z/0-9 — response.py:19-20
- 2.3 — insert — ambiguity — empty-string query param = omitted; enum filter outside its set is `ERR_INVALID_REQUEST`; free-text filters are exact-equality; undeclared params ignored — response.py:63-118
- 2.3 — insert — ambiguity — `created_at` ties (routine under the frozen clock) break by creation order; `id` never orders anything — db.py:70-74
- 2.4 — insert — ambiguity — client instants accept `Z`, +/-HH:MM (converted to UTC) or no zone (read as UTC), 1-9 fractional digits; output always 3 digits, truncated — db.py:83-123
- 2.7 item 3 — insert — ambiguity — absent/empty body = `{}`; non-object or unparseable JSON = `ERR_INVALID_REQUEST`; explicit `null` == omitted — validation.py:20-41
- 2.7 item 4 — revise — mismatch — path existence runs *ahead* of body schema on every path-addressed operation — routes/*.py
- 3.1 — revise — mismatch — `licensed_state_codes` entries are two ASCII letters in either case stored verbatim, distinctness judged case-insensitively — providers.py:23-24
- 3.2 — revise — mismatch — address `state_code` accepted in either case and stored verbatim — addresses.py:26
- 3.2 — insert — ambiguity — every pre-existing cohort row is version-bumped on registration, including one already `DUPLICATE_FLAGGED` (verified live: version 1->3) — addresses.py:48-54
- 3.2 — insert — ambiguity — `resolution_note` is validated but not surfaced in the dwelling's representation — addresses.py:74
- 3.3 — insert — ambiguity — `last_3mo_income_cents` defaults to 0 — subscribers.py:29-30
- 3.3 — insert — ambiguity — `VERIFIED_ELIGIBLE`/`ENROLLED` applicants may open further checks, posture and `version` untouched when no edge fires; the `DE_ENROLLED->PROSPECT->ELIGIBILITY_PENDING` pair costs exactly one version — subscribers.py:146-152
- 3.3 — insert — ambiguity — `ERR_SUBSCRIBER_BARRED` outranks both basis gates — subscribers.py:101
- 3.3 — revise — mismatch — `verifier_reason_code` may accompany any outcome; missing `matched_benefit` on a benefit-claimed `MATCH` is `ERR_INVALID_REQUEST` reported ahead of the not-pending precondition; `matched_benefit` written only on `MATCH` — eligibility.py:31-41
- 3.3 — insert — ambiguity — `MATCH` bumps the applicant's version even in `DUPLICATE_HOLD`; `NO_MATCH`/`DOCUMENTATION_REQUIRED` leave the applicant untouched unless the edge fires — eligibility.py:53-67
- 3.3 — revise — mismatch — resubmission cap is "twice at most", not "three times" (internal PRD inconsistency vs `MAX_DOCUMENTATION_RESUBMISSIONS = 2`) — eligibility.py:83
- 3.5 — insert — ambiguity — sweep reads no body and ignores the carrier's own `status` (a `SUSPENDED` carrier is swept) — providers.py:56-59
- 4 intro — insert — ambiguity — trailing slash tolerated; unrouted path -> 404 `ERR_NOT_FOUND`; wrong method -> 405 `ERR_INVALID_REQUEST` — app.py:31,43-51

Verified with no change needed: the section-5 catalogue matches `errors.py` exactly (60 codes, identical statuses); peer-isolation coverage in 2.1 matches every `require_provider_owner`/`require_subscriber_owner` call site; all list endpoints use `created_at` ASC.

### Pass 2 — slice: routes/{enrollments,devices,transfers}.py, services/cascades.py

No copy; edited in place with 19 Edits. 121,163 -> 124,941 chars. 11 ambiguity-pins, 8 mismatch-revisions.

- 3.4 p1 — revise — mismatch — the `certified_address_id` vs applicant `address_id` mismatch is tested only after all four body references resolve and before the ownership check, and no cross-reference between `eligibility_check_id` and `subscriber_id` is tested at all — enrollments.py:45-53
- 3.4 p3 — insert — ambiguity — `recert_due_date` is stamped at `00:00:00.000Z` and rendered as a full instant — enrollments.py:106
- 3.4 canonical cascade — insert — ambiguity — the applicant row is rewritten (version +1) on every de-enrollment even when its posture does not move — cascades.py:73-78
- 3.5 Recording usage — insert — ambiguity — a usage write rewrites the benefit row alone; carrier and dwelling untouched — enrollments.py:192-193
- 3.5 cure — insert — ambiguity — a supplied `usage_at` is ignored on the cure path; the forward-only anchor rule does not apply there — enrollments.py:174-182
- 3.5 Answering the notice — insert — ambiguity — all four attestation inputs mandatory with intake bounds; `last_3mo_income_cents` has no default here — enrollments.py:203-207
- 3.5 ineligible arm — insert — ambiguity — `recert_last_responded_at` stays null and the notice/deadline fields are left as written — enrollments.py:249-250
- 3.1 handset stocking — revise — mismatch — the `ERR_PROVIDER_NOT_ACTIVE` gate precedes the `imei` uniqueness test — devices.py:29-35
- 3.6 p1 — revise — mismatch — device issuance is `ProviderAgent` only, not open to `ProgramAdministrator` — devices.py:111
- 3.6 What issuance writes — revise — mismatch — `device_issuance_count` is an incremented issuance-event counter, not a recount of distinct handsets — devices.py:164
- 3.6 Returns — revise — ambiguity — `device_status` resets to `AWAITING_DEVICE` regardless of `benefit_status` — devices.py:199-203
- 3.7 p1 — revise — mismatch — the **losing** carrier opens the port and the gaining carrier decides it (was inverted) — transfers.py:29-32,100-103
- 3.7 Opening — insert — ambiguity — body references resolve `enrollment_id` before `target_provider_id` — transfers.py:26-27
- 3.7 Opening — insert — mismatch — fixed bar order: benefit `ACTIVE`, then porting freeze, then same-carrier — transfers.py:34-48
- 3.7 Accepting — revise — mismatch — benefit `ACTIVE` is tested ahead of the gaining carrier's status and cap — transfers.py:119-129
- 3.7 Link three — insert — ambiguity — link three fires only when an `ISSUED` handset was actually reclaimed — transfers.py:143-156
- 3.7 Rejecting — revise — ambiguity — `acceptance_note`/`rejection_note` must be >=1 character when supplied — transfers.py:115,175
- 3.9 The reinstatement — revise — mismatch — `cure_deadline_at` is also cleared on reinstatement — cascades.py:106
- 3.8 The final pricing — insert — ambiguity — selection reads the benefit's current carrier reference, so a mid-month port is priced in full by the gaining carrier and not at all by the losing one — cascades.py:205

### Pass 3 — slice: routes/{claims,cases,clock}.py, services/{calc,derive}.py

No copy; edited in place with 16 Edits. 124,941 -> 129,143 chars. 15 ambiguity-pins, 4 mismatch-revisions (19 changes).

- 2.4 — insert — ambiguity — every declared field is always present in a representation, a valueless field rendered as explicit JSON `null` rather than omitted — derive.py:223-430
- 2.4 — revise — ambiguity — the clock reply's `data` holds `current_utc` as its single field — clock.py:18
- 3.8 Drafting — insert — ambiguity — a draft is born with `certifying_officer_ref`, `filed_at`, `sample_drawn_by_ref` null — claims.py:67-71
- 3.8 Filing — revise — **mismatch** — the four gates run claim-`DRAFT` -> carrier-`ACTIVE` -> month-closed -> audit-hold; `certifying_officer_ref` is 1-64 chars — claims.py:108,112-126
- 3.8 Risk scoring — revise — **mismatch** — a read evaluates the score live from the five inputs, while the copy stored on the benefit row (what a draw ranks by and snapshots) only moves on a write that touches the benefit, so a dwelling-status change alone leaves it behind — derive.py:206,336
- 3.8 Drawing — revise — **mismatch** — the 1-50 `sample_size` range is tested before the pool, so size 0 on an empty pool reports `ERR_INVALID_SAMPLE_SIZE` — claims.py:150-165
- 3.8 Drawing — insert — ambiguity — the per-benefit line breakdown is retained internally from filing and is not surfaced on the claim — claims.py:157
- 3.8 Ranking — revise — ambiguity — creation order is the final tie-break below `created_at` — claims.py:167-169
- 3.8 Draw result — insert — ambiguity — response is an array in `selection_rank` order; the carrier is not rewritten — claims.py:192-196
- 3.8 Draw result — insert — ambiguity — a drawn sample's `finding`, `finding_note`, `adjudicated_by_ref`, `disallowed_support_cents` are null, not zero — claims.py:184-187
- 3.8 Adjudicating — insert — ambiguity — `finding_note` has no upper bound but must be >=1 char when supplied; stored, null when omitted — claims.py:231,246
- 3.8 Adjudicating — insert — ambiguity — a settled claim's refusal code is `ERR_CLAIM_NOT_FILED`, and the sample's own status is read first — claims.py:239-243
- 3.8 Fail-fast — insert — ambiguity — samples left in `DRAWN` on a failed claim can never be adjudicated — claims.py:242
- 3.8 Fail-fast — insert — ambiguity — the de-enrolling findings fire only while the benefit is still `ACTIVE` — claims.py:294-297
- 4 table — revise — **mismatch** — audit-sample list is also filterable by `status` — claims.py:210
- 3.9 Filing — insert — ambiguity — body refs resolve `subscriber_id` then `enrollment_id`; the `Subscriber` bar is measured against `subscriber_id` alone; `ProviderAgent` unconfined here; no other row rewritten — cases.py:29-32,64
- 3.9 Assigning — insert — ambiguity — `reviewer_ref` 1-64 chars; the assignability test precedes the round cap; rewrites the case alone — cases.py:99-111
- 3.9 Deciding — insert — ambiguity — `decision_rationale` is 1-2000 chars; a decision rewrites the case row alone apart from the reinstatement cascade — cases.py:122,152-171
- 3.9 Identity bars — insert — ambiguity — the remand count is internal and unsurfaced; only `review_round` is visible — cases.py:132

**Completeness statement (pass 3):** within its slice pass 3 walked every endpoint, gate and ordering in `claims.py`/`cases.py`/`clock.py`, every constant/formula/tier boundary in `calc.py` (all already pinned: rates, FPG table, windows, 395-day freeze, risk weights, penalty tiers, half-up rounding), and every serializer in `derive.py`, then mechanically verified field coverage in both directions — all 118 serializer keys appear in the PRD, and every backticked identifier in the PRD exists in the implementation. Combined with passes 1 and 2, every implementation behavior in the union of the three slices now traces to a PRD sentence. The single residual under-determination stated loosely on purpose is the stored-vs-live risk-score copy, worded so both the live read and the draw's snapshot are correct.

Step 9 edited documentation only — no file under `implementation/`, `test_suite/` or `test_helpers/` was modified — so the Step 7 green sweep (8/8 rounds at 102/102, `results.{1..8}.json` on disk) remains the standing test result. PIPELINE COMPLETE.

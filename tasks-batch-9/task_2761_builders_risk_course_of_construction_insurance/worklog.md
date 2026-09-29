## Step 1: Create task directory — 2026-09-04T17:29:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2761_builders_risk_course_of_construction_insurance and its workspace/ subdirectory. Index 2761 was pre-assigned by the orchestrating caller (no ./tasks/ scan performed, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T19:53:00.000Z

All three scaffold artifacts are complete, parse cleanly, and pass the scaffold linter.

Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2761_builders_risk_course_of_construction_insurance/SCAFFOLD.yaml` — 2672 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_2761_builders_risk_course_of_construction_insurance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2433 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_2761_builders_risk_course_of_construction_insurance/SCAFFOLD_CORNER_DESIGN.yaml` — 6123 lines

SCAFFOLD.yaml counts (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys present)
- entities 11, endpoints 57, state_machines 9, concurrency_rules 3, calculations 10, validations 50, errors 58, roles 6
- complexity profile: layers `dual_variant_calculation`, `cascading_side_effects`, `optimistic_concurrency`, `derived_field_reconciliation`; `role_model: segregation_of_duties`; `entity_topology: flat`; `state_machine_shape: parallel`; `consistency_model: immediate`

§1.8 (difficulty design): 9 rules / 21 instances

§1.9 (corner design): 9 sections / 107 instances (73 full test recipes + 34 `excluded_because` stubs)
- entities 13, state_machines 17, calculations 18, validations 25, errors 15, endpoints 8, rbac 6, cross_cutting_complexity_layers 4, consistency_model 1

Verification
- Every one of the 58 error IDs is referenced by at least one §1.8/§1.9 instance (no untriggerable errors).
- No duplicate instance names across the union of both design files; every instance is exactly one of full/stub; all stubs cite an existing `rule_id / instance_name` with a rationale.
- The difficulty directive phrase appears nowhere in SCAFFOLD.yaml; no sibling task directory was read.
- Linter: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1292 calls scanned across 21 + 73 recipe-bearing instances.)

Orchestrator verification: independently grepped all three YAMLs for the difficulty-directive phrase "harder than expert" — zero hits, so the known leak-via-scaffold failure mode did not occur. No post-Step-2 strip needed.

## Step 3: Copy shared files — 2026-09-04T19:54:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2761_builders_risk_course_of_construction_insurance/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T20:11:00.000Z

PRD generation and verification are complete.

## Output
`workspace/PRD.md` — **462 lines**, 102,808 bytes, built via 12 bounded heredoc appends (no single giant Write, so no 64k truncation). `tail -30` confirms the file ends on the last row of the §5 error table (`| ERR_PAYMENT_EXCEEDS_RESERVE | 422 |`) — a completed final section, not mid-sentence. No audit footer, no Hard Contract report, no scaffold references inside the document.

## Section list
- `# Builders Risk Course Of Construction API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` (2.1 Operators/Roles/Identity · 2.2 API Response Structure verbatim · 2.3 Pagination · 2.4 Common Resource Properties and the Audit Trail · 2.5 Cents, Days and Rounding Discipline · 2.6 The Logical Clock · 2.7 Cascade Discipline · 2.8 Path Resolution and Reverse Lookups · 2.9 Stale-View Rejection on Parent Records · 2.10 Segregation of Duties and Authority Limits · 2.11 Order of Evaluation · 2.12 The Premium Ledger and the Erosion Reconciliation)
- `## 3. Business Logic & Workflows` (3.1 Project Intake and Loss-Control Screening · 3.2 Assembling the Policy: the Coverage Schedule · 3.3 The Named Insured and Loss-Payee Schedule · 3.4 Rating, Referral, Binding and Inception · 3.5 Site Exposures: Off-Site Storage and Testing Windows · 3.6 Schedule Slip: Extension Endorsements · 3.7 Loss Adjustment: Valuation Basis and the Allocation Waterfall · 3.8 Paying, Voiding and Reopening · 3.9 End of Term: Expiry and Cancellation)
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Coverage confirmation (all machine-verified against SCAFFOLD.yaml)
- **Endpoints: 57 / 57.** All 57 §1.5 paths appear; the §4 table parses to exactly 57 method+path rows; every row's Authorized Role(s) cell matches the scaffold's `authorized_roles` set exactly (0 mismatches).
- **Errors: 58 / 58.** All 58 ids present; all 58 HTTP statuses match the scaffold exactly; all 58 also appear in the §1–§4 narrative, not only in the catalogue table.
- **Contract 1 — Field-Name Coverage: PASS.** 116 required identifiers → 0 missing. 63 request-body identifiers → 0 missing. 17 query/path params → 0 missing. All 6 role names verbatim. All states across all 9 machines present. All entity enum literals present.
- **Contract 2 — Rule Coverage: PASS.** All 50 validations' error ids surface in prose with conditions; §2.11 encodes the full priority ordering 10→114; all 3 concurrency_rules documented in §2.9 with write endpoint, OCC field, error id and 412; all 10 calculations rendered as operator-free ordered prose. Both `project_risk_score` variants documented as distinct named bases ("submission basis" §3.1, "audit basis" §3.6) including all three audit-basis input differences and the claim-status inclusion/exclusion lists.
- **Contract 3 — §3 Path Purity: PASS.** 309 distinct backtick tokens scanned between §3 and §4: 0 paths, 0 bare HTTP methods, 0 method+path combos.
- **§2.2 verbatim: PASS** (byte-identical diff against the canonical section).
- **Style gates: PASS.** 0 fuzzy quantifiers, 0 operator syntax.

Both read prohibitions honoured: neither design YAML was opened, grepped, or referenced; no sibling task directory read.

## Scaffold inconsistencies found, and the readings chosen
1. **`referral_load_pct` on reopen (genuine contradiction).** The policy state machine's `QUOTED → DRAFT` transition clears `referral_load_pct` to 0; the `POST /policies/{id}/reopen` endpoint's side_effects say it is preserved. Wrote the endpoint's reading (preserved), as the endpoint block is the more specific contract for that route.
2. **Screening ineligibility trigger.** Endpoint mentions only score >= 90; state machine adds `engineering_grade == D`. Wrote the union (grade D or score at least 90 -> INELIGIBLE) per the state machine guard.
3. **Claim `loss_date` bounds.** Entity field description implies a half-open term; validation priority 82 makes both bounds inclusive. Followed the validation (both inclusive).
4. **`in_force_policy_count` on inception.** State machine says "increments by 1", endpoint says "sets = 1" — equivalent under the one-live-policy rule; written as "becomes 1".

Five scaffold rules carry no `error_id`, so each was stated as a precondition/refusal in prose without inventing a code: the `existing_structure_value_cents`-must-be-zero rule on NEW_CONSTRUCTION, the substantial-completion date bounds, the MATERIALS_ON_SITE part requirement at rating, the bind-time MATERIALS_ON_SITE + EXISTING_STRUCTURE sublimit sum ceiling against `insured_tiv_cents`, and the clock-at-or-after-`term_start_date` requirement for inception.

Orchestrator verification: PRD.md is 462 lines ending on the final `ERR_PAYMENT_EXCEEDS_RESERVE` row of the §5 catalogue table — a real section boundary, so the known doc-generator truncation failure did not occur. Grep for the difficulty directive phrase in PRD.md returns 0 hits.

## Step 5: Generate unit tests — 2026-09-04T20:51:30.000Z

Queue A (difficulty) is finished, all four queue-B agents have reported, and the whole tree is verified.

## Output

`test_helpers/` — 8 files, 1584 lines
`__init__.py` 46 · `types.py` 322 · `api_errors.py` 129 · `constants.py` 108 · `api_client.py` 252 · `test_users.py` 64 · `factories.py` 212 · `assertions.py` 256 · `fixtures.py` 452

`test_suite/` — `conftest.py` 50 plus 21 test modules, 6509 lines
Queue B: `test_01_entities.py` 600 · `test_02_state_machines.py` 611 · `test_03_calculations.py` 563 · `test_04_validations.py` 962 · `test_05_errors.py` 730 · `test_06_endpoints.py` 366 · `test_07_rbac.py` 371 · `test_08_cross_cutting.py` 274
Queue A: `test_10_dual_valuation_bases.py` 153 · `test_11_quote_premium_stack.py` 69 · `test_12_allocation_rounding.py` 78 · `test_13_extension_premium_order.py` 74 · `test_14_claim_axes.py` 75 · `test_15_endorsement_revision_cycle.py` 101 · `test_16_expiry_cascade.py` 89 · `test_17_payment_cascade.py` 93 · `test_18_validation_priority.py` 154 · `test_19_boundary_precision.py` 240 · `test_20_cross_entity_state.py` 241 · `test_21_resource_temporal_overlap.py` 187 · `test_22_compensating_invariants.py` 221

## Totals and coverage

- **115 tests**, every one carrying exactly one `Design:` line as the last docstring line; an AST audit confirms 115 tags, zero untagged, zero dual-tagged, zero dangling (each name matched verbatim against a `- name:` in the right yaml).
- **Queue A (difficulty): 21 / 21 instances translated, 42 tests**, minimum 2 per instance.
- **Queue B (corner): 73 / 73 non-stub instances translated, 73 tests.** The remaining 34 corner instances are stubs and correctly got no test; every agent grep-verified its stubs' `difficulty_instance:` pointers resolve to exactly one difficulty instance (no broken pointers).
- Per corner section (translated / non-stub): entities 13/13, state_machines 10/10, calculations 8/8, validations 18/18, errors 11/11, endpoints 5/5, rbac 5/5, cross_cutting_complexity_layers 2/2, consistency_model 1/1.

## Verification

`python3 -m compileall test_helpers test_suite` passes; every file `py_compile`d after each chunked append; `__pycache__` cleaned. A static audit resolves every `api_client.*`, `fx.*`, `ApiErrorId.*` and every `from test_helpers…` / `from prd_bench_local_runner.testing …` import against the real objects (nothing missing), and every test's fixture parameters exist in `conftest.py`. Nothing was written under `workspace/`, and no `test_helpers/` or `test_suite/` exists there.

## Skipped instances

**None** — no instance failed the two-condition filter outright, and there is no `skip`/`xfail`/placeholder anywhere. Three sub-probes inside otherwise-translated instances were dropped because the PRD does not uniquely derive their outcome: `ERR_COVERAGE_PART_MISSING` on a quote with no materials part (the precondition is stated, no error id is attached to it), `sublimit_cents: 0` (`ERR_INVALID_REQUEST` vs `ERR_SUBLIMIT_EXCEEDS_LIMIT` is ambiguous since §2.11 only promises non-negativity), and a `LossPayee` listing another payee's payments (scoped-empty-list reads as well as a 403).

## Design-index defects where the PRD won (worth relaying to the scaffold owner)

1. `extension_premium_pinned_evaluation_order_mode_c` — its 1000000 gross loss under a 25000000 deductible denies the claim, so the audit basis could never reach the 85 needed for the asserted 1.25 reslip; raised to 100000000.
2. `clock_expiry_cascades_...` — asserts `closed_n == 2` while its own setup schedules three ACTIVE parts; asserted 3.
3. `slip_reason` values `LABOR`, `SUPPLY_CHAIN` and free text are outside the PRD enum; mapped to `LABOR_SHORTAGE` / `MATERIAL_DELAY` / `WEATHER`.
4. Agents' finds: `ERR_INTERESTS_NOT_ACKNOWLEDGED` is 409 not 422; a new claim's `continuing_pm_weeks` is 0 not null; a QUOTED policy's `written_premium_cents` is 0 not null; a superseded reopened policy's `quoted_premium_cents` is null not retained; `existing_structure_value_cents` on NEW_CONSTRUCTION and stale `expected_project_version` replays are illegal in several recipes; `covered_cents` / `net_indemnity_cents` are not PRD field names.
5. One helper bug fixed that the sub-agents flagged but could not touch: `assertions.assert_pagination_meta` asserted a `total` meta key; it now asserts the PRD's `total_count` / `has_more` (no callers were affected).

Orchestrator note: Steps 5 and 6 were launched as two background agents seconds apart rather than in a single message. Step 6's prompt carried an absolute prohibition on reading `test_helpers/`/`test_suite/`, and its returned summary confirms neither directory was read, listed, globbed or grepped — so the isolation intent held even without the physical "directory does not exist yet" guarantee. Verified independently that no `test_helpers/` or `test_suite/` stray landed under `workspace/`.

## Step 6: Generate implementation — 2026-09-04T20:51:35.000Z

## Done — implementation complete and smoke-verified

**Location:** `workspace/implementation/`

### File list (line counts)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `exec python3 app.py`, guarded `pip install`, `cd $(dirname $0)` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 86 | blueprint registration under `/builders-risk`, `ApiError`/404/405/400/`HTTPException`/500 handlers, `0.0.0.0:$PORT` (default 10000) |
| `util.py` | 68 | ids, ISO-8601 3-frac formatting, `Decimal` half-up, day arithmetic |
| `errors.py` | 89 | full error-id → HTTP status catalogue + `ApiError` |
| `enums.py` | 103 | every declared value set + pinned `ALLOCATION_ORDER` |
| `db.py` | 76 | in-memory dicts, logical clock (`2026-08-01T00:00:00Z` epoch), `new_row`/`touch`/`ordered` |
| `response.py` | 69 | `meta`/`response_type`/`data` envelope, list `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | 183 | `X-User-ID`/`X-User-Role` auth, RBAC, body schema helpers, pagination/filters |
| `lookup.py` | 87 | path + body FK resolution with per-collection 404 ids |
| `calc.py` | 303 | quote premium, risk scores, slip factor/extension pricing, delay indemnity, 7-step allocation waterfall, return premium, facility/testing window geometry |
| `recompute.py` | 182 | premium ledger, erosion reconciliation, 4-hop cascade, expiry sweep |
| `routes/projects.py` | 176 | 7 endpoints |
| `routes/policies.py` | 396 | 16 endpoints |
| `routes/coverage_parts.py` | 108 | 3 |
| `routes/interests.py` | 104 | 3 |
| `routes/endorsements.py` | 247 | 6 |
| `routes/claims.py` | 265 | 6 |
| `routes/payments.py` | 162 | 4 |
| `routes/notices.py` | 103 | 3 |
| `routes/facilities.py` | 87 | 5 |
| `routes/assignments.py` | 88 | 3 |
| `routes/clock.py` | 21 | 1 |
| **Total** | **~3014** | |

### Endpoint coverage: 57 / 57

Enumerated Flask's `url_map` at boot: exactly 57 method+path pairs, matching SCAFFOLD.yaml's endpoint table one-for-one (7 project, 16 policy, 3 coverage-part, 3 interest, 6 endorsement, 6 claim, 4 loss-payment, 3 notice, 5 facility, 3 assignment, 1 `_clock`).

### Smoke-boot result: PASS

`python3 -m compileall` clean; server booted three times from `bash start.sh` on ports 18761/18762, each killed by exact PID (no `pkill`/`killall` was ever used). Verified end-to-end against the live server: full quote→bind→incept arc (premium 9,480,000 / 6,801,840 on two rated risks), referral SoD, interest ack ownership + duplicate-priority + pct-exceeded refusals, bind completeness gates, storage assignment with too-distant/duplicate-site-code/capacity-exceeded/touching-window cases and `committed_value_cents` recompute on release, testing notice mitigation-plan + 24h hot-work conflict + double-decision, endorsement OCC 412 → SoD → return-for-info → resubmit → `ERR_MANAGER_APPROVAL_REQUIRED` on an Underwriter approval → UWM approve (dates + ledger moved) → rescind restoring `written_premium_cents` exactly, claim adjust waterfall (reconstruction uplift + PM soft-cost line + single occurrence deductible: indemnity 105,824,000, uncovered 2,500,000), settle SoD, payment issue → void restoring `paid_cents` to 0, DELAY claim (14 indemnified days × 500,000 = 7,000,000, no uplift/deductible on the delay line, SETTLED→CLOSED on full payment), short-rate cancellation return (4,366,623), and the clock-driven expiry sweep (`expired_policy_count: 1`, `closed_coverage_part_count: 2`).  Envelope, 401/403/404/405/412/422 statuses and `ERR_*` ids all render as specified.

### Notes
- Store is strictly in-memory and empty on every boot — no seeding, no SQLite, no disk/`/tmp` cache (grep for `seed`/`preload` returns only docstrings asserting the absence).
- `test_helpers/`, `test_suite/` and all sibling task directories were never read, listed, globbed or grepped; the build came only from `PRD.md` + `SCAFFOLD.yaml` + `INSTRUCTION.md`.
- Two PRD-over-scaffold fidelity choices preserved: `reopen` keeps `referral_load_pct` (§3.4), and bind requires *every* interest `ACKNOWLEDGED` (not just LENDERs). Storage-assignment gate order follows §2.11 (`SUSPENDED` → `WINDOW_OUTSIDE_POLICY_TERM` → `TOO_DISTANT` → `CAPACITY_EXCEEDED`), not the §3.5 prose reading order.

## Step 7: Run tests and iterate — 2026-09-04T21:13:00.000Z

All 8 rounds clean.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one fix batch, one verification sweep).

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and was uniquely derivable; all 20 failures were test-artifact bugs, not PRD-silence cases.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added `_canonicalise_instants` plus an `ApiClient._request` override that rewrites every ISO 8601 UTC instant in a response body to whole-second precision. 18 of the 20 failures were purely fractional-second width (`2026-09-01T00:00:00.000Z` vs `2026-09-01T00:00:00Z`) on client-supplied date fields (`planned_start_date`, `projected_completion_date`, `term_end_date`, `adjusted_completion_date`, `loss_date`, `effective_date`, `bound_at`, `reported_at`, `released_at`). PRD §2.4 pins the three-fractional-digit rendering only for `created_at`/`updated_at`; for every other instant §2.5 states the governing rule as "Datetimes are compared to whole-second precision", and the suite was already internally inconsistent — `test_06`/`test_07`/`test_08` used the existing `same_instant()` helper while `test_01`/`test_02`/`test_04`/`test_05`/`test_10`/`test_13`/`test_15`/`test_16` used raw string `==`. Canonicalising once in the client makes every site obey the PRD comparison rule without weakening any asserted value.

**Fixes applied to `test_suite/`:**
- `test_18_validation_priority.py::test_an_underwriter_may_decide_the_endorsement_inside_the_authority_limit` — asserted `approved["decided_by"]`, raising `KeyError`. PRD §2.1 names the field `decided_by_user_id` ("`requested_by_user_id` and `decided_by_user_id` on an extension endorsement"); corrected to the PRD field name.
- `test_22_compensating_invariants.py::test_rescission_restores_the_written_premium_by_appending_a_reversal` — asserted `extension_ap_total_cents == 785479` *after* the rescission. PRD §3.4 defines it as "the signed sum of the `EXTENSION_AP` and `EXTENSION_AP_REVERSAL` rows only", so 471287 + 314192 − 314192 = 471287. The test's own docstring was self-contradictory ("which now nets the reversal, stays at 785479"). Corrected the expected value to 471287 and the docstring; the pre-rescission assertion of 785479 at line 57 is correct and was left alone.

**Fixes applied to `implementation/`:** none — no implementation defect was found. The premium-summary signed sum, the endorsement audit stamp and every date derivation were already PRD-faithful.

**Final sweep (8 parallel rounds, `setsid nohup`, per-test-server isolation):**

| round | passed/total |
| --- | --- |
| 1 | 115/115 |
| 2 | 115/115 |
| 3 | 115/115 |
| 4 | 115/115 |
| 5 | 115/115 |
| 6 | 115/115 |
| 7 | 115/115 |
| 8 | 115/115 |

No flakiness observed: the first sweep's 20 failures were identical in all 8 rounds, and the second sweep was clean in all 8. `worklog.md` untouched.

Orchestrator verification: independently parsed all eight `workspace/implementation/results.*.json` files (each ~35 KB, all written at 21:03) — every one reports `passed=115, total=115, failed=0`, so the clean-sweep claim is backed by real artifacts rather than an unrun sweep.

Step 8 decision: NOT skipped. Step 7 ran 2 iterations with 1 `test_helpers/` fix and 2 `test_suite/` fixes. Although there were 0 `implementation/` fixes, the two test_suite corrections are PRD-mismatch signals (`decided_by` vs `decided_by_user_id`, and the `extension_ap_total_cents` signed-sum reading), and the api_client canonicalisation marks a PRD instant-precision silence — all three are exactly the sites Step 8 exists to pin. The skip condition requires zero fixes of every kind, which is not the case here.

## Step 8: Finalize PRD — 2026-09-04T21:22:00.000Z

Done.

## Line counts
- `PRD.md`: 462 lines / `PRD_FINALIZED.md`: 464 lines — **+2 lines (+0.43%)**, one inserted paragraph, nothing else altered.

## Changes
- **§2.4 Common Resource Properties** — *insert* — added one paragraph making the ISO-8601 rendering rule uniform: **every** datetime-valued field in a response body is rendered with exactly three fractional digits and a trailing `Z` (not just `created_at`), enumerating `updated_at`, the echoed client dates, the self-stamped instants, a ledger row's `effective_date`, and the clock's `current_utc`; explicitly framed as a presentation rule that leaves §2.5's whole-second *comparison* rule intact — `implementation/response.py:23` (`serialize` → `fmt_dt`) and `implementation/util.py:22-29`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 uniform datetime rendering**
- **(a) Subject:** the rendered fractional-second width / suffix of every datetime the service emits, and the boundary between rendering and comparison.
- **(b) Impl paths enumerated:**
  - `implementation/util.py:22-29` `fmt_dt` — single formatter, always `%Y-%m-%dT%H:%M:%S.` + `microsecond // 1000` + `Z`; normalises naive → UTC and any offset → UTC.
  - `implementation/response.py:8-28` `serialize` — the *only* JSON rendering path; recurses into dicts/lists, so nested rows (allocation lines, list pages) route through `fmt_dt` too. `response.py:33` `_meta()` uses the same formatter for `api_request_timestamp` (already PRD-pinned at three digits), including on error bodies.
  - Grep for every alternative rendering (`isoformat`, `strftime`, `fmt_dt` outside `util.py`) across `implementation/` — no second path exists, so the claim is genuinely universal.
  - `implementation/middleware.py:122-130` `get_dt` → `util.py:32-43` `parse_dt` — every client-supplied date is parsed into a `datetime` (accepts `Z`, offset, naive, date-only) and stored as such, so none of them survives as a raw echoed string. All 17 call sites confirmed via grep: `routes/projects.py:36,37,100`, `routes/policies.py:31,32,238`, `routes/notices.py:26,27`, `routes/assignments.py:22,23`, `routes/endorsements.py:48,114`, `routes/claims.py:26`, `routes/clock.py:16`.
  - `implementation/db.py:39-52` (`new_row`/`touch` set `created_at`/`updated_at` from the clock) and `implementation/recompute.py:21-29` (`effective_date` stored as a datetime) — confirms self-stamped instants are datetimes, not strings.
  - Exhaustive grep of datetime-bearing keys across `routes/`, `recompute.py`, `calc.py` to make the enumeration exact and avoid naming a field that does not exist: the 17 found keys plus `created_at`/`updated_at`; notably there is **no** `voided_at`, so it is not listed.
  - `routes/clock.py:20` — `current_utc` is returned as a `datetime` through `ok()`, hence also three digits; cross-checked against §2.6's "reads exactly `2026-08-01T00:00:00Z`" (a value statement) and `db.py:9` `CLOCK_EPOCH`.
- **(c) Wording adjustments made:** (1) framed the rule as covering "every datetime-valued field a response carries" rather than listing only the nine fields from the Step 7 failure set, so off-site paths (`acknowledged_at`, `revised_completion_date`, `window_*`, `cancel_effective_date`, `actual_substantial_completion_date`, list/nested payloads, `api_request_timestamp`) are not accidentally excluded; (2) said "regardless of the fractional width or UTC offset the client originally supplied" instead of naming a rounding/truncation behaviour, leaving sub-millisecond handling under-determined rather than falsely pinned; (3) added the `2026-08-01T00:00:00.000Z` clock example so the new rule cannot be read as contradicting §2.6's bare-`Z` prose; (4) added the closing "presentation rule only … still *compared* to whole-second precision as §2.5 states" so the insert does not tighten §2.5's comparison semantics anywhere (e.g. window containment, clock gates, cancellation dating).

## Items deliberately left unpatched
- `test_18` `decided_by` → `decided_by_user_id`: PRD §2.1/§3.6 already name the field, and `routes/endorsements.py:71,171,183` (plus `routes/notices.py:54,88`) use exactly that name. Pure fixture bug.
- `test_22` `extension_ap_total_cents` expected value: PRD §3.4's "signed sum of the `EXTENSION_AP` and `EXTENSION_AP_REVERSAL` rows only" matches `routes/policies.py:382-385` verbatim (no status filter, reversal included as a negative). Pure fixture arithmetic bug.
- No `implementation/` fixes existed in Step 7, so no mismatch-driven edits were warranted beyond the one above.

## Step 9: Complete PRD — 2026-09-04T21:45:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were forbidden from copying and edited in place). Partition: pass 1 = app/util/errors/enums/db/response/middleware/lookup + routes/projects, routes/policies, routes/clock; pass 2 = calc, recompute + routes/coverage_parts, routes/interests, routes/endorsements; pass 3 = routes/claims, routes/payments, routes/notices, routes/facilities, routes/assignments. Each pass received the prior pass's hand-off leads and was required to verify them against the code rather than accept them.

### PASS 1 (core + project/policy/clock) — 20 changes: 18 ambiguity-pins, 2 mismatch-revisions
Source PRD_FINALIZED.md 464 lines / 103,854 chars → 464 lines / 108,243 chars (+4,389 chars, 0 line delta; all in-paragraph).
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + twenty upper-case alphanumerics — `util.py:19`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the only timestamp read from real wall-clock time, not the logical clock — `response.py:33`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; empty string → default — `middleware.py:141-161`
- §2.3 — insert — ambiguity — default ordering ties broken by insertion order (matters because the logical clock makes `created_at` collide constantly) — `db.py:60`
- §2.3 — insert — ambiguity — out-of-enum filter → `ERR_INVALID_REQUEST`, empty filter → absent; identifier filters matched literally, unknown id → empty page not 404 — `middleware.py:164-179`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` come from the logical clock, so rows share `created_at` and `updated_at` can be numerically unchanged while `version` bumps — `db.py:41-55`
- §2.4 — insert — ambiguity — accepted datetime input forms (`Z`, offset, naive→UTC, bare date→UTC midnight); otherwise `ERR_INVALID_REQUEST` — `util.py:32-44`
- §2.5 — insert — ambiguity — `_cents`/day/week/version fields accept JSON integers only (bool, `1000.0`, `"1000"` rejected); booleans must be JSON booleans — `middleware.py:70-93`
- §2.5 — insert — ambiguity — whole-day duration is the floor of elapsed time; reversed pair yields a negative count — `util.py:47-49`
- §2.5 — insert — ambiguity — the two ratio fields accept any finite number or numeric string, then range/decimal-width/value-set checked — `middleware.py:96-119`
- §2.6 — insert — ambiguity — clock accepts any instant including a backward move; no monotonicity, nothing rolled back — `routes/clock.py:17-18`
- §2.11 step 8 — insert — ambiguity — absent body = empty object; unparseable/non-object body = `ERR_INVALID_REQUEST`; JSON `null` treated as omitted; strings must be non-empty; unknown properties ignored — `middleware.py:29-56`
- §3.1 — insert — ambiguity — non-zero `existing_structure_value_cents` on `NEW_CONSTRUCTION` is `ERR_INVALID_REQUEST`, not `ERR_EXISTING_STRUCTURE_NOT_APPLICABLE` — `routes/projects.py:38-42`
- §3.1 — insert — ambiguity — substantial-completion date failures are `ERR_DATE_RANGE_INVALID`, evaluated *after* the `UNDER_CONSTRUCTION` state test — `routes/projects.py:101-115`
- §3.4 — insert — ambiguity — missing `MATERIALS_ON_SITE` at quote → `ERR_COVERAGE_PART_MISSING`, after the project rateable-state check — `routes/policies.py:104-112`
- §3.4 — insert — ambiguity — the preserved `referral_load_pct` is never read by rating; a load re-applies only via a fresh referral disposition — `routes/policies.py:156-160` + `calc.py:78`
- §3.4 — revise — ambiguity — schedule-vs-TIV breach at bind → `ERR_SUBLIMIT_EXCEEDS_LIMIT` — `routes/policies.py:196-200`
- §3.4 — revise — mismatch — INITIAL ledger row carries `memo` of exactly `bind` and null `reverses_sequence_no` — `routes/policies.py:204-206`
- §3.4 — insert — ambiguity — inception before `term_start_date` → `ERR_INVALID_POLICY_STATE` — `routes/policies.py:217-220`
- §3.9 — revise — mismatch — RETURN_PREMIUM row carries `memo` of exactly `cancellation return` — `routes/policies.py:253-259`
- §5 preamble — insert — ambiguity — off-catalogue transport errors `ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INTERNAL`/500, same envelope — `app.py:46-76`, `errors.py:73-75`

Verified clean in pass 1's partition: all 24 route role lists match `authenticate(...)`; §5 statuses match `errors.py:ERROR_STATUS` row for row; `enums.py` matches every PRD enum listing; §2.11 order honoured throughout projects/policies; premium-summary's seven fields and premium-transactions' `sequence_no` ordering already pinned.

### PASS 2 (calc, recompute, coverage_parts, interests, endorsements) — 11 changes: 8 ambiguity-pins, 3 mismatch-revisions
464 lines / 108,243 chars → 466 lines / 112,525 chars.
- §2.10 — revise — mismatch — "Four pairings" → five; return-for-info also enforces the `requested_by_user_id` comparison — `routes/endorsements.py:90`
- §2.10 — revise — mismatch — the authority limit does *not* precede "every existence and state check": it follows path resolution and JSON parsing, precedes SoD / `decision` enum / state, and tests the *raw* `decision` for literal `APPROVE` — `routes/endorsements.py:149-158`
- §2.11 step 3 — revise — mismatch — same correction to the numbered order — `routes/endorsements.py:147-158`
- §2.9 — insert — ambiguity — `expected_..._version` must be a non-negative JSON integer; negative/fractional/string is `ERR_INVALID_REQUEST` at step 8, not the stale-version code at step 11 — `routes/endorsements.py:43` (also `policies.py:30`, `payments.py:43`)
- §2.12 — insert — ambiguity — erosion reconciliation is *evaluated* over every coverage part but only *mutates* (and version-bumps) parts whose `eroded_cents`/`available_cents` actually change, so one payment bumps exactly one part — `recompute.py:60-63`
- §3.2 — revise+insert — ambiguity — a patch supplying neither `sublimit_cents` nor `condition_code` is `ERR_INVALID_REQUEST`, before the policy editable-status test; `available_cents` recomputed even on a condition-only patch; parent policy `version` untouched — `routes/coverage_parts.py:72-77,100-101`
- §3.3 — revise — ambiguity — acknowledgement bumps only the interest's `version`, never the parent policy's — `routes/interests.py:91-93`
- §3.6 resubmit — insert — ambiguity — bumps only the endorsement's `version`, no SoD comparison, no policy-state test — `routes/endorsements.py:106-141`
- §3.6 approval hop four — revise — ambiguity — `memo` exactly `extension approval`, `reverses_sequence_no` null, `effective_date` is the pre-hop-two `term_end_date`, policy bumped once despite two writes — `routes/endorsements.py:186-199`
- §3.6 rescission — revise — ambiguity — reversal row's `effective_date` is the logical clock at rescission; `memo` exactly `extension rescission`; matched to that endorsement's own AP row, not the latest — `routes/endorsements.py:224-233`, `recompute.py:38-42`
- §3.7 step three — insert — ambiguity — synthetic `SOFT_COST` line takes `coverage_part_id` from the policy's ACTIVE SOFT_COST part, or null when none is scheduled (no refusal); once appended it competes for the step-four deductible — `calc.py:211-226`
- §3.7 step five — insert — ambiguity — a line with no matching ACTIVE part has zero room, allocates nothing, whole net falls to `uncovered_cents` — `calc.py:248`

Pass 2's verdicts on pass 1's leads: (1) the "unclaimed" calc functions were mostly a false alarm — `quote_premium`, both risk-score bases, `slip_factor_for`, `price_extension`, `delay_indemnity`, all seven waterfall steps, `return_premium`, `windows_overlap`, `facility_peak_exposure`, `testing_window_conflict` are already uniquely pinned; the one real hole was the synthetic SOFT_COST line. (2) The conditional-touch mismatch is only partly real — `recompute_erosion`'s conditional part-touch is observable and was pinned; `recompute_committed_value` / `recompute_in_force_policy_count` conditional bumps are unobservable because every call site necessarily changes the total. (3) `_endorsement_id` matching was already pinned; wording strengthened to exclude a "latest AP row" reading. (4) `audit_basis_score`'s no-policy case is unreachable (all three call sites require IN_FORCE and bind's `ERR_ACTIVE_POLICY_EXISTS` guarantees uniqueness), so deliberately not pinned.

### PASS 3 (claims, payments, notices, facilities, assignments) — 17 changes: 14 ambiguity-pins, 3 mismatch-revisions
466 lines / 112,525 chars → 466 lines / 117,652 chars (+5,127 chars; all in-paragraph).
- §2.8 — insert — ambiguity — body FK resolution order when a body names two FKs: `policy_id` before `facility_id`, `claim_id` before `payee_interest_id` — `assignments.py:19-20`, `payments.py:39-40`
- §2.1 — revise — mismatch — LossPayee read rights omitted individual loss payments; also pinned that an explicit foreign `payee_interest_id` filter is refused rather than silently narrowed — `payments.py:134-140,158-161`
- §2.3 — insert — ambiguity — a facility's storage-assignment sub-resource is filterable by `status` — `facilities.py:82`
- §3.5 — insert — ambiguity — `distance_from_site_miles` input/echo discipline (any finite number or numeric string, any decimal width, redundant fraction dropped on output) — `facilities.py:21`
- §3.5 — insert — ambiguity — facility `status` is required and the only patchable property; a no-op status patch is `ERR_INVALID_REQUEST` at step 8, not a state code — `facilities.py:48-50`
- §3.5 — insert — ambiguity — storage commitment does not bump the covering policy's or project's `version` — `assignments.py:51-64`
- §3.5 — insert — ambiguity — notice scheduling leaves project `version` untouched, requires no project status, and a null `engineering_grade` never triggers the plan requirement — `notices.py:15-58`
- §3.5 — revise — mismatch — `rejection_reason` is optional even on `REJECT` (stays null); a reason sent with `APPROVE` is discarded — `notices.py:67,85-87`
- §3.7 step one — insert — ambiguity — `loss_items` supplied on a `DELAY` claim are discarded unread, not schema-checked — `claims.py:61-66`
- §3.7 — insert — ambiguity — a `RELEASED` assignment qualifies only when `released_at` is *strictly* later than `loss_date` — `claims.py:93-95`
- §3.7 — insert — ambiguity — the zero-indemnity denial branch still stamps `adjustment_basis`, `continuing_pm_weeks`, `adjusted_by_user_id` — `claims.py:187-189`
- §3.7 — insert — ambiguity — on `DENY`, `uncovered_cents`/`delay_days_indemnified` forced to 0; `adjustment_basis`/`continuing_pm_weeks`/`loss_items` neither read nor schema-checked; stored basis/weeks/adjuster stamp left as-is — `claims.py:131-142`
- §3.7 — insert — ambiguity — both settle preconditions fail with `ERR_INVALID_CLAIM_STATE`, incl. an ADJUSTED claim re-adjusted down to zero indemnity — `claims.py:212-216`
- §3.8 — revise — mismatch — payee must also carry a non-null `loss_payee_priority`; either failure is `ERR_PAYEE_NOT_ON_POLICY` — `payments.py:58-62`
- §3.8 — insert — ambiguity — the availability test reads the matching part whatever its `status`, so a CLOSED bucket still caps payments under an EXPIRED/CANCELLED policy — `payments.py:82-90`
- §3.8 — insert — ambiguity — on void the payment axis is re-derived from surviving ISSUED payments, adding the unenumerated `PARTIALLY_PAID → PARTIALLY_PAID` self-loop — `payments.py:16-30`
- §3.8 — insert — ambiguity — reopen's policy-state refusal is `ERR_INVALID_POLICY_STATE` and runs after claim state *and* the loop counter; every derived money figure, allocation line and the payment axis are retained — `claims.py:222-237`

Pass 3's verdicts on pass 2's leads: (1) `payments._apply_axes` derive-from-scratch is *partially* wider — on issue it is provably equivalent to §3.8's enumeration (`amount_cents >= 1` makes `paid <= 0` unreachable; the reserve gate makes `paid > indemnity` unreachable), but on void it is wider by exactly the `PARTIALLY_PAID` self-loop, which was pinned. (2) `claims.settle`'s null-stamp guard is unobservable (`None == "<user id>"` is already False), so no edit; the adjacent genuine gap — the unnamed settle refusal code — was pinned instead. (3) `calc.return_premium`'s `DivisionByZero` on a sub-24-hour term was left entirely alone: out of pass 3's partition, and Step 9 is documentation-only.

### Latent implementation defect recorded, deliberately not fixed
`calc.return_premium` divides by `original_term_days`, so cancelling a policy whose term is under 24 hours would raise `DivisionByZero` → HTTP 500. Step 9's mandate is documentation-only and the 8-round sweep is green, so no implementation change was made and no PRD prose asserts the sub-24-hour case. Recording it here as the durable trace.

### Totals and integrity
48 changes across the three passes (40 ambiguity-pins, 8 mismatch-revisions). `PRD_COMPLETED.md` is 466 lines / 117,652 chars versus `PRD_FINALIZED.md`'s 464 lines / 103,854 chars — a +13.3% char delta over 92 changed lines, so the file is NOT byte-identical to its source and the scan demonstrably ran. Orchestrator-verified: 5 `##` sections intact, all 58 error rows present, all 57 endpoint rows present, file ends on the final `ERR_PAYMENT_EXCEEDS_RESERVE` catalogue row. `PRD.md` and `PRD_FINALIZED.md` were left untouched at 462 and 464 lines.

## Post-Step-9 confirmation sweep — 2026-09-04T21:54:37.000Z

Step 9 is documentation-only, but a final 8-round `setsid nohup` sweep was run afterwards to prove the three doc passes left the code untouched. All 8 rounds: 115/115, failed=0. `workspace/implementation/results.{1..8}.json` on disk are these final passing rounds. Log at `workspace/sweep_final.log` (spliced/interleaved by design — the results files are the authority).

Pipeline complete: Steps 1–9 all executed, `workspace/PRD_COMPLETED.md` written.

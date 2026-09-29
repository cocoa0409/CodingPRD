## Step 1: Create task directory — 2026-09-04T12:06:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2723_winery_direct_to_consumer_shipping_compliance and its workspace/ subdirectory. Index 2723 was pre-assigned by the orchestrating invocation; no scan of ./tasks/ was performed to avoid colliding with the ~32 concurrent pipelines on this host.

## Step 2: Generate scaffold — 2026-09-04T13:37:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2729 | 139,933 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2135 | 148,264 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5824 | 405,890 |

Top-level keys verified: `SCAFFOLD.yaml` carries only §1.0–§1.7 keys (no design keys); the other two carry exactly `scaffold_difficulty_design` / `scaffold_corner_design`.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 57   §1.1 entities declared: 14
  §1.8 instances scanned: 21    §1.9 instances scanned: 57
  Calls scanned (§1.8+§1.9): 1317
```

Three scaffold defects were found and fixed while writing §1.9 (each was a real internal inconsistency, not a test-recipe error): `ERR_PROHIBITED_DESTINATION` referenced a non-existent `reason` value `PROHIBITED_ZIP`; the `POST /dtc/state-rules/{id}/prohibited-zips` description repeated that phantom enum member; and `POST /dtc/state-rules` listed `min_purchaser_age` / `renewal_lead_days` as required although §1.1 declares defaults (21 / 60) — now `min_purchaser_age?` / `renewal_lead_days?`.

## Inventory (SCAFFOLD.yaml)

- **Domain**: `api_prefix: /dtc`, archetype `compliance_audit` + `quota_allocation`, `expert_plus`, topology `flat`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.
- **14 entities**: Winery, StateRule, ProhibitedZip, StatePermit, CarrierProgram, CarrierEnrollment, Consumer, Order, OrderLine, Shipment, ClubSubscription, ComplianceException, VolumeLedgerEntry, TaxRemittance.
- **9 state machines** — Order carries two independent dimensions (compliance DRAFT/CLEARED/REJECTED/OVERRIDE_PENDING/SUSPENDED_PERMIT and fulfillment UNFULFILLED/LABELED/IN_TRANSIT/DELIVERED/RETURNED), plus StatePermit (incl. renewal cycle and lazy expiry), Shipment (cyclic via reroute), CarrierEnrollment, ClubSubscription (weather hold + compliance suspension), Winery, ComplianceException, TaxRemittance, Consumer verification.
- **2 concurrency rules**: `order-create-stale-consumer` (`expected_consumer_version` on POST /dtc/orders) and `enrollment-create-stale-winery` (`expected_winery_version` on POST /dtc/carrier-enrollments), both 412 `ERR_STALE_VERSION`.
- **9 calculations**: order charge chain (12 steps: liters → subtotal → shipping tiers → club discount → excise with small-producer credit and large-format surcharge and per-shipment cap → per-line-allocated sales tax → pre-fee total → handling fee → total), waterfall shipping allocation, consumer rolling volume, winery annual state liters, dual-variant consumer risk score (SCREENING/AUDIT), dual-basis remittance due amounts (ACCRUAL/DELIVERY), club run selection, renewal calendar, small-producer credit.
- **30 ordered validations** (priority 15 → 95), **57 endpoints** (POST/GET only — no PATCH/PUT/DELETE), **45 errors**, **5 roles** (PlatformAdmin, ComplianceOfficer, WineryOperator, CarrierAgent, Consumer).

## §1.8 distribution — 9 rules / 21 instances

dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 3 · compensating_invariant 2 (every rule ≥ 2).

## §1.9 distribution — 9 sections / 82 entries (57 full recipes + 25 `excluded_because` stubs)

| Section | Recipes | Stubs |
|---|---|---|
| entities | 12 | 0 |
| state_machines | 10 | 4 |
| calculations | 8 | 5 |
| validations | 9 | 5 |
| endpoints | 6 | 1 |
| errors | 3 | 5 |
| rbac | 5 | 0 |
| complexity_layers | 3 | 5 |
| consistency_model | 1 | 0 |

Checks run on the pair: zero duplicate names across the union of both design files; every stub names a real §1.8 instance and carries no `test_recipe`; all 45 error ids appear in at least one `assert` block (547 assert lines total). Both §1.2.1 concurrency rules have their own stale-version recipe, and all four active complexity layers plus the `immediate` consistency model are represented.

**Orchestrator note (not from the subagent):** the scaffold generator copied the difficulty directive line ("Generate task harder than expert level!") into SCAFFOLD.yaml's `scenario:` block. Because SCAFFOLD.yaml is the doc generator's only input, that line would have leaked into PRD.md, which the invocation forbids. The orchestrator deleted exactly that one line from `scenario:` before Step 4; the scenario text itself is untouched and all other keys are unmodified.

## Step 3: Copy shared files — 2026-09-04T13:38:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2723_winery_direct_to_consumer_shipping_compliance/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T13:56:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **501 lines / 107,915 bytes**, built via 12 chunked `cat >> PRD.md <<'PRDEOF'` appends (no single large Write).

**Section outline**
- `# Winery DTC Shipping Compliance API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Resource Identity, Timestamps and Versioning · 2.6 Stale-Read Protection on the Two Headroom-Consuming Writes · 2.7 Liters, Cents and Rounding Discipline · 2.8 Path Resolution, Request Shape and Referential Integrity · 2.9 Order of Evaluation · 2.10 Cascades, Compensating Movements and Derived Counters · 2.11 One Order, Two Independent Status Dimensions (11 subsections)
- `## 3. Business Logic & Workflows` — 3.1 Standing Up the Compliance Landscape · 3.2 Destination-State Licensing · 3.3 Carrier Enrollment and the Adult-Signature Chain · 3.4 Consumers, Identity Verification and the Volume Ledger · 3.5 Placing an Order: Lines, Liters and the Charge Chain · 3.6 Screening, Rejection and the Override Path · 3.7 Fulfillment: Labels, Scans, Reroutes and Returns · 3.8 The Wine Club · 3.9 State Reporting: Remittances, Amendments and the Renewal Calendar (9 subsections)
- `## 4. Endpoint Definitions` — status-code paragraph + 4-column table (Method | Path | Description | Authorized Role(s))
- `## 5. Error Code Catalogue` — 2-column table (Error ID | HTTP Status Code)

**Hard Contract results (machine-verified against SCAFFOLD.yaml)**
- **Contract 1 — Field-Name Coverage: PASS.** 142/142 `entities[].fields[].name` present as inline-backticked tokens, 0 missing. 97/97 distinct `input`/`query_params`/`path_params` identifiers present, 0 missing (includes `expected_consumer_version`, `expected_winery_version`, `current_utc`).
- **Contract 2 — Rule Coverage: PASS.** 45/45 scaffold error ids appear in prose and in the §5 table, 0 extras, 0 HTTP-status mismatches. All 30 validation priorities expressed as an explicit ordered ranking in §2.9. Both `concurrency_rules` expressed with write endpoint + occ field + `ERR_STALE_VERSION` + 412. All 9 state machines: every state name present; all 44 transitions verified present as adjacent from→to pairs. All 17 `calculations[].constants` embedded numerically in business context (constant *names* deliberately not exposed, per SKILL line 194). Sibling-branch symmetry held for APPROVED/DENIED, ACCRUAL_BASIS/DELIVERY_BASIS, SCREENING/AUDIT risk variants, IN_TRANSIT/EXCEPTION return paths.
- **Contract 3 — §3 Path Purity: PASS.** Zero `/`-prefixed backtick tokens, zero bare HTTP-method tokens, zero method+path tokens in §3; also zero raw `/dtc` occurrences anywhere in §3.

**Endpoint table fidelity:** all 57 scaffold endpoints present, 0 missing, 0 extra, and 0 role-list differences against `endpoints[].roles` (including `POST /_clock/set_current_utc` → PlatformAdmin).

**Untruncated:** file ends at the final `ERR_NOTHING_TO_REMIT | 422 Unprocessable Entity` table row of §5 — a real section boundary, not mid-sentence. No audit footer or contract report leaked into the document, and no fuzzy hedging words or "pseudocode"/"TODO" markers appear.

**Constraints honored:** neither design yaml was opened, grepped, or referenced; no sibling task directory was read.

**Orchestrator truncation re-check (independent of the subagent):** `wc -l` = 501; `grep '^#\{1,3\} '` shows all five top-level sections with §2 at 11 subsections and §3 at 9 subsections; `tail -12` ends on a complete §5 table row. Not truncated. Also re-confirmed the difficulty directive did not reach PRD.md (`grep -c -i "harder than expert"` = 0).

## Step 5: Generate unit tests — 2026-09-04T14:44:00.000Z

Stage 2 complete and fully verified. Final state:

## Files written

**`test_helpers/` (task root, 9 files, 2262 lines)** — `constants.py` 282, `types.py` 300, `api_errors.py` 60 (all 45 PRD §5 errors, registers the status map), `api_client.py` 338 (`DtcApiClient`, one method per §4 endpoint), `assertions.py` 255, `factories.py` 286, `test_users.py` 67, `fixtures.py` 606, `__init__.py` 68.

**`test_suite/` (18 test files + conftest, 9411 lines)** — conftest 28; test_01 491, test_02 431, test_03 271, test_04 521, test_05 382, test_06 453, test_07 374, test_08 518, test_09 696, test_10 694, test_11 901, test_12 855, test_13 499, test_14 294, test_15 720, test_16 362, test_17 162, test_18 759.

## Verification (all mandated checks run)

- `python3 -m py_compile` clean on all 27 emitted .py files.
- `pytest --collect-only`: **179 tests collected, zero collection errors** (155 test functions, expanded by parametrize).
- An AST-based audit cross-checked every `Design:` tag against a re-parse of both design yamls: **0 problems** — no untagged test, no dual-tagged test, no dangling tag, no tag pointing at an `excluded_because:` stub, and the tag is the last docstring line everywhere.
- Nothing was written inside `workspace/`; `test_helpers/` and `test_suite/` are at the task root.

## Coverage: 155 tests, zero instances skipped

**Queue A — Difficulty: 21/21 live instances (note: the index holds 21, not 19), 80 tests, all at or above the 2-test floor.** resource_temporal_overlap 13, compensating_invariant 11, transitive_cascade 11, boundary_precision_check 9, cross_entity_state_dependency 9, priority_pair_validation_conflict 8, dual_variant_calc 7, non_linear_state_machine 7, combinatorial_formula 5.

**Queue B — Corner: 57/57 non-stub instances, 75 tests**, each instance at or above the 1-test floor. calculations 15, validations 13, entities 12, rbac 12, state_machines 10, endpoints 6, complexity_layers 3, errors 3, consistency_model 1. All **25 `excluded_because:` stubs were correctly left untranslated.**

No instance failed the PRD-first filter at instance level, so there are no gaps. Sub-assertions were dropped where the design outran or contradicted the PRD.

## Key findings (PRD won in every case)

- **Reroute rewrites the order:** the design asserted `ship_to_zip` unchanged after an accepted reroute; PRD §3.7 rewrites it to the reroute ZIP. The design's real intent (frozen tax basis, no ledger movement) is asserted separately.
- **Four separate recipes open a remittance period that has not closed** (`period_end` after the logical clock, which PRD §3.9 forbids). Workers re-based the clock/window and preserved every asserted figure rather than encoding an impossible 201.
- **Two error-catalogue mismatches:** design said `ERR_ORDER_NOT_CLEARED` is 422 (PRD §3.7: 409); design wanted `ERR_INVALID_STATE_TRANSITION`/409 for a DELIVERED scan missing `signed_by` (PRD: `ERR_INVALID_REQUEST`/400).
- **`volume-summary.per_state` inner field names are nowhere in the PRD** — found independently by four workers. Those assertions were re-expressed through the PRD-named `Consumer.rolling_liters_by_state` / `rolling_liters_settled_by_state`. Same treatment for undeclared list filters (§2.3 declares only `limit`/`offset`) and for `renewal_calendar.report_period` internals.
- **`return_credit_count` after a terminal rejection is genuinely ambiguous** (design says 0; §3.4's structural definition derives 1, since §3.6 appends a `RETURN_CREDIT` row on that path) — asserted neither value. Likewise `Winery.version` on a first enrollment create, and tracking-number uniqueness, are read rather than predicted.
- **One infrastructure defect found and fixed:** `build_override_pending_order` defaulted to `seeded_liters=22.500`, which sums to exactly the 27.000 L TX limit and therefore *clears* per §3.6, so the `override_pending_order` fixture could not produce its own state. Default raised to 25.000 with a comment; no test depended on the old default.

## Step 6: Generate implementation — 2026-09-04T14:31:00.000Z

Implementation complete and smoke-verified.

## Files written (all under `workspace/implementation/`)

**Foundation** — `app.py` (64), `clock.py` (111), `store.py` (72), `errors.py` (61), `response.py` (44), `middleware.py` (42), `validate.py` (205), `rounding.py` (39), `requirements.txt` (1, `Flask==3.0.3`), `start.sh` (10, executable)

**Services** (`services/`) — `charges.py` (150), `volume.py` (270), `screening.py` (138), `orders_svc.py` (142), `permits.py` (116), `club_svc.py` (105), `remit_svc.py` (98), `calendar_svc.py` (120), `derive.py` (72), `serialize.py` (280)

**Routes** (`routes/`) — `common.py` (109), `reference.py` (225), `permits.py` (167), `carriers.py` (110), `consumers.py` (188), `club.py` (169), `orders.py` (220), `shipments.py` (239), `remittances.py` (156)

Total 3,723 lines. `python3 -m py_compile` passes on every `.py` file; `__pycache__` removed afterwards.

## Layout

`app.py` registers eight blueprints (reference, permits, carriers, consumers, club, orders, shipments, remittances), sets `url_map.strict_slashes = False`, and installs three error handlers (`ApiError` → catalogued id/status, `HTTPException` → envelope with `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INVALID_REQUEST`, bare `Exception` → `ERR_INTERNAL` 500). Routes do only ordering + shape + scoping; every calculation lives in `services/`. Storage is 14 plain dicts in `store.py`, reset per process, nothing seeded.

Key design points: all winery/consumer/subscription counters are **derived on read** (`services/derive.py`), so an override-approved clearance can never double-accrue excise or allotment; the screening ladder is one `evaluate()` walked in PRD 2.9 order, reused band-limited at label time; the logical clock is the sole "now", defaulting to exactly `2026-08-01T00:00:00Z`.

## `start.sh`

`set -euo pipefail`, `cd "$(dirname "$0")"`, a **guarded** `pip install` (only when `import flask` fails, to avoid boot contention across concurrent rounds), then `exec python3 app.py`. `app.py` binds `host="0.0.0.0"`, `port=int(os.environ.get("PORT", "10000"))`, `threaded=True`, no reloader, foreground.

## Smoke boot (port 18723, killed by its own pid only — no broad pkill)

A 38-call end-to-end pass came back green: winery → state rule → carrier program → permit file+activate → enrollment + carrier decision → consumer + id-verification → order → screen (`CLEARED`) → label → PICKUP/EXCEPTION/REROUTE/DELIVERED scans → volume summary → club subscription + weather-hold + release + club run (`generated_count` 1) → remittance create/file/remit (SoD 403 for the filer, 200 for a second officer) → renewal calendar → ledger entry → clock set. Negative paths confirmed: missing headers 401, wrong role 403, unknown id 404, bad body 400, unknown route 404, wrong method 405, trailing slash 200.

Money chain cross-checked by hand on the smoke order (6×750 ml, 3500¢/bottle, TX): 4.500 L, shipping 2490¢, excise 76¢ (90¢ gross less the 15% small-producer credit, 13.5 → 14 half-up), sales tax 1879¢, `pre_fee_total` 25445 ≥ 20000 so fee 0, `total_cents` 25445 — matches PRD §3.5 step by step.

Isolation held: nothing under `test_helpers/`, `test_suite/`, the corner/difficulty design files, or any sibling task directory was read or listed; all writes were inside `workspace/implementation/` (smoke scripts live in `/tmp`).

**Orchestrator note:** Steps 5 and 6 were launched as concurrent background agents. Verified after both exited: `test_helpers/` (9 files) and `test_suite/` (19 files incl. conftest) are at the task root, and `find workspace -name 'test_*'` returns nothing — no test artifacts drifted into `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T15:03:00.000Z

Exactly two files changed, worklog untouched, no stray directories. Done.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Both failures traced to verbatim PRD sentences and survived the unique-derivability check, so neither qualified for deletion.

**Fixes applied to `test_helpers/`:** none — the helper layer was already PRD-faithful (I audited `api_client.py`, `fixtures.py`, `factories.py`, `constants.py`, `assertions.py`, `test_users.py`; the canonical 4.500 L TX order constants reconcile exactly against the §3.5 twelve-step chain).

**Fixes applied to `test_suite/`:**
- `test_15_rbac_and_ownership.py::test_the_refused_cross_role_attempts_change_nothing` — asserted the order sat at `CLEARED`/`UNFULFILLED` after its own `_cleared_and_labeled` helper had produced a label. PRD §3.7 says verbatim "The order moves `UNFULFILLED` → `LABELED`", so the expected fulfillment dimension is `LABELED`. Fixed the assertion toward PRD (STEP 2 test bug — the implementation was already correct at `routes/shipments.py:107`). Nothing was weakened: the test still asserts an exact two-dimension state, and the sibling test that reads `screened` pre-label was already correct.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/volume.py::_utilisation_factor` — genuine precision defect. The risk-score utilisation term computed `Decimal(liters) / Decimal(limit)` and only then multiplied by 30. With 1.500 L against a 4.500 L limit the quotient becomes `0.3333…` at 28-digit precision, so `30 ×` it yields `9.999999999999999999999999999`, which floors to **9** instead of the exact **10**. That cost a whole point and left `risk_score_screening` at 49, one short of the `ELEVATED` threshold — PRD §3.4 requires "30 multiplied by the selected state's liters divided by that state's per-consumer limit, truncated downward", whose exact value here is 10, and §3.4 makes 50 the tier boundary. Now carries the ratio as an exact `Fraction` (used for both the greatest-ratio selection and the final `math.floor(30 × ratio)`), so a product whose true value is a whole number can never truncate down through finite-precision division. Verified against several liters/limit pairs including the 30-point cap and the empty-map zero.

**Final sweep:** all 8 parallel rounds **179/179 passed**, 0 failed, 0 errors — union of failures across rounds is empty. All eight `results.{1..8}.json` exist, are complete JSON, and are consistent in size (~55.6 KB each). No reaping signature: no server log ended in `Terminated`, and the rounds finished independently.

Note on the first iteration: the 2 failures were identical and deterministic in all 8 rounds (177/179 every round), so neither was load-induced flakiness — the parallel sweep confirmed both were real defects rather than contention artifacts.

**Orchestrator verification (independent of the subagent):** re-read all eight `results.{1..8}.json` directly — every file reports `passed=179, failed=0, errors=0, total=179, skipped=0`. Sweep artifacts are real, not claimed. Step 8 is therefore NOT skipped: Step 7 applied 1 `implementation/` fix and 1 `test_suite/` fix.

## Step 8: Finalize PRD — 2026-09-04T15:12:00.000Z

Done. One edit was warranted; the other Step 7 item was a pure test bug.

## Line counts
- `PRD.md`: 501 lines / 107,915 bytes
- `PRD_FINALIZED.md`: 501 lines / 108,297 bytes
- Line delta: 0 (0.0%); byte delta +382 (+0.35%). `diff` shows exactly one changed line (245).

## Changes
- **§3.4 (Consumer risk, third/utilisation factor)** — *revise* — pinned that both the greatest-ratio state selection and the `30 × liters ÷ limit` product that gets truncated are evaluated as exact rational arithmetic rather than a finite-precision quotient multiplied afterwards, with the 1.500 L / 4.500 L → exactly 10 (not 9) worked value — `implementation/services/volume.py:158-184` (`_utilisation_factor`, `Fraction` ratio + `math.floor(30 * ratio)`).

## Per-edit pre-edit search log

**Edit 1 — §3.4 utilisation term**
- (a) Subject: the utilisation factor `f3` — how the liters/limit ratio is computed, which state it selects, and how the `30 ×` product is truncated; plus anything else in the system that divides liters by a limit or truncates a derived number downward.
- (b) Impl paths enumerated: `grep -rn "utilisation|utilization|_utilisation_factor|floor("` across `implementation/` returned only `services/volume.py:158` (definition), `:179` (the `math.floor(30 * ratio)` + 30-cap + 0-floor), and the two call sites `:235` (screening variant, `settled` map) and `:238` (audit variant, `all_time` map) — both variants route through the same single function, so one PRD sentence covers both and stays consistent with §3.4's later two-variant paragraph (line 247). Also read `services/volume.py` in full (`rolling_map`, `all_time_map`, `rolling_state_liters`, `_score`, `consumer_derived`) to confirm the maps fed to the factor are already 3dp half-up liters, `rounding.py` (`dec`, `rhu_liters`, `floor_cents`) to confirm the only other downward truncation is `floor_cents`, used by the sales-tax waterfall — a different subject in §3.5 that my wording does not reach — and PRD §2.7 (lines 115-125) to confirm no global precision rule would conflict. Checked §3.7 (lines 315-325) for the other Step 7 item: it already says verbatim "The order moves `UNFULFILLED` → `LABELED`", matching `routes/shipments.py:107`, so no PRD edit (that item was a test-side bug).
- (c) Wording adjustments made to keep all paths consistent: scoped the exactness claim to the ratio and the product only, so it applies identically to both the screening and audit call sites and does not bleed into the §3.5 `allocated_shipping_cents` truncation or the 3dp half-up liters rounding of §2.7. Deliberately left untouched (no claim either way, to avoid a false universal) the impl's clamp of a negative factor to 0, its skipping of states with no state rule or a non-positive limit, and the `_score` min/max clamps — all pre-existing and outside the Step 7 site's traceable subject.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` confirms exactly one changed line (245) and `tail` confirms PRD_FINALIZED.md still ends on the final §5 error-table row — the Edit-tool patch path did not truncate the 108 KB document.

## Step 9: Complete PRD — 2026-09-04T15:40:00.000Z

Run as THREE sequential file-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden to `cp` and edited in place). Partition was by implementation module so no single subagent had to hold 108 KB of PRD plus 3,723 lines of implementation at once. Totals: **60 changes — 48 ambiguity-pins, 12 mismatch-revisions.** Source `PRD_FINALIZED.md` 501 lines / 108,297 bytes → `PRD_COMPLETED.md` 511 lines / 130,423 bytes (+10 lines, +22,126 bytes, +20.4%).

### Pass 1 — foundation slice (app, clock, store, errors, response, middleware, validate, rounding, start.sh) — 12 ambiguity-pins, 2 mismatch-revisions

- §2 preamble — insert — ambiguity — storage holds nothing at startup; every list answers empty `data` / `total_count` 0 until a create runs — `store.py:18-33`, `app.py:3-4`
- §2.1 — insert — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty → 401 — `middleware.py:13`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `response.py:9-13`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, so same-instant requests share it — `response.py:19`
- §2.2 — revise — ambiguity — error envelope covers 4xx **and 5xx** — `app.py:52-54`
- §2.2 — insert — ambiguity — message wording non-contractual; unexpected fault → HTTP 500 `ERR_INTERNAL` — `errors.py:60-61`, `app.py:52-54`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` (never clamped); empty-string param = omitted; enum and boolean (`true/false/1/0`, case-insensitive) query-param rules — `validate.py:161-205`
- §2.3 — **revise** — **mismatch** — PRD said ties are broken "rather than insertion luck"; impl sorts `(created_at, _seq)`, i.e. by server creation sequence — `store.py:70-72`
- §2.4 — insert — ambiguity — `current_utc` required ISO 8601 (Z/offset normalized, date-only = midnight UTC); endpoint answers 200 with `data.current_utc` at 3 fractional digits; clock may be set backwards, no monotonicity, and this is the only mutator — `clock.py:13-42,60`
- §2.5 — insert — ambiguity — canonical hyphenated UUIDv4 `id` — `store.py:38-39`
- §2.5 — insert — ambiguity — `updated_at` equals `created_at` on a fresh row — `store.py:46-57`
- §2.7 — insert — ambiguity — liters are JSON numbers, never strings; `1.5` ≡ `1.500` — `rounding.py:35-39`
- §2.7 — insert — ambiguity — half-up means away from zero for negative values (signed ledger): −0.0015 → −0.002 — `rounding.py:20-27`
- §2.8 — insert — ambiguity — routing precedes the §2.1 header check: unrouted path → 404 `ERR_NOT_FOUND`, undeclared method → 405 `ERR_METHOD_NOT_ALLOWED` (both without headers), other framework 4xx → `ERR_INVALID_REQUEST`; trailing slash insignificant — `app.py:22-34,45-50`
- §2.8 — insert — ambiguity — absent/empty body = `{}`; non-object or unparseable JSON → 400; explicit `null` ≡ omitted; no coercion — `validate.py:16-114`
- §5 — insert — ambiguity — added rows `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 (transport-level ids `errors.py` does not carry) — `app.py:22-29,52-54`
- Verified needing no change: §5's 45 domain rows are an exact id→status match with `errors.py:ERROR_HTTP`; `has_more`, per-response `meta` field sets, and `version` starting at 1 already pinned.

### Pass 2 — services slice (charges, volume, screening, orders_svc, permits, club_svc, remit_svc, calendar_svc, derive, serialize) — 13 ambiguity-pins, 2 mismatch-revisions

- §2.8 — insert — ambiguity — date/instant request fields are validated by parsing but stored and echoed **byte-for-byte as supplied**; only server-computed dates render canonically — `validate.py:117-127`, `serialize.py:63,117-143,261`
- §2.7 — insert — ambiguity — a state rule's limit liters are subject to 3dp half-up as read back — `serialize.py:38,40`
- §3.2 — insert — ambiguity — expiry observation is a *sweep*: a screen sweeps every permit of that winery for the destination state, a calendar read sweeps every permit in any state, version-bumping bystanders — `permits.py:27-36`, `screening.py:89`, `calendar_svc.py:49`
- §3.3 — insert — ambiguity — with several qualifying `APPROVED` enrollments the family is judged together (any one satisfies each rule); a state with `requires_carrier_program` false never reaches the signature rule — `screening.py:100-108`
- §3.4 — insert — ambiguity — the rolling liters maps carry a key only for states with ≥1 in-window entry (absent, not 0) — `volume.py:94-104`
- §3.4 — insert — ambiguity — "widest `per_consumer_period` window in play" resolved: periods of states in the consumer's own entries, falling back to all configured rules, then `ROLLING_12_MONTHS`; `return_credit_count` applies no settled filter, `denied_exception_count` no window — `volume.py:134-145,207-227`
- §3.4 — insert — ambiguity — utilisation factor floored at 0 as well as capped at 30; states with no rule or non-positive limit passed over — `volume.py:166-184`
- §3.4 — **revise** — **mismatch** — the screening variant's denial count uses the same *widest* span as `return_credit_count`, not a per-state period — `volume.py:228-232`
- §3.6 — insert — ambiguity — with several non-revoked permits for one state exactly one is judged, by preference ACTIVE-covering-today → ACTIVE → EXPIRED → RENEWAL_FILED → PENDING, then `created_at` ASC then creation sequence — `permits.py:50-69`
- §3.6 — **revise** — **mismatch** — the in-force rule accepts `ACTIVE` **or** `EXPIRED` (EXPIRED falls through to the lapse rule); PRD had said "status must be `ACTIVE`" — `screening.py:93-97`
- §3.6 — revise — ambiguity — consumer headroom excludes **this order's own** `SHIPMENT_ACCEPTED`/`RETURN_CREDIT` entries (never a `MANUAL_ADJUSTMENT`), and the accumulated figure is rounded to 3dp before `total_liters` is added — `screening.py:125-131`, `volume.py:67-91`
- §3.6 — revise — ambiguity — same own-order exclusion and rounding order for winery annual headroom — `screening.py:134-138`, `volume.py:115-131`
- §3.8 — insert — ambiguity — `consumed_shipments` counts orders that reached `CLEARED` at least once and only ever grows — `derive.py:43-51`
- §3.9 — insert — ambiguity — `permits_expiring` entries carry exactly nine named members and no `id`/`created_at`/`updated_at`/`version` — `calendar_svc.py:74-85`
- §3.9 — insert — ambiguity — `reports_due` covers only states of permits surviving the calendar filter, deduped per state; seven members incl. nested `report_period` **and** the same two dates repeated flat; `report_filed` compares parsed dates — `calendar_svc.py:37-108`
- Deferred item resolved: `charges.py:59` `floor_cents` needs no edit — §3.5's "truncated downward to a whole cent" already pins ROUND_FLOOR and the negative direction is unreachable (pool and liters are provably non-negative/positive), so ROUND_FLOOR and truncate-toward-zero cannot diverge. The remainder is always < line count, so the cyclic extra-cent hand-out never wraps.
- Deferred item resolved: serializers echo the **raw** date string (confirmed at every storage site across routes); only `clock.date_iso` values are canonical. Pinned in §2.8.

### Pass 3 — routes slice (common, reference, permits, carriers, consumers, club, orders, shipments, remittances) — 23 ambiguity-pins, 8 mismatch-revisions

- §2.1 — insert+revise — ambiguity+mismatch — pinned list auto-scoping (omitted `winery_id`/`consumer_id` filter silently replaced by the caller's own id; a foreign id of the caller's own family is `ERR_FORBIDDEN_RESOURCE_OWNER`; the other family's filter untouched; the shipment list confines a `WineryOperator` through each shipment's order by *dropping* rows, not refusing), and revised the "ownership runs before existence" claim — that holds only when the owner is legible from the request; row-derived ownership resolves the row first, so its 404 wins — `routes/common.py:84-101`, `routes/permits.py:62`, `routes/shipments.py:43-46`
- §2.9 — revise — mismatch — ownership band annotated with its §2.1 position — `routes/shipments.py:43-46`
- §2.9 — insert — mismatch — one exception to the domain ranking: reroute tests state change before destination ZIP — `routes/shipments.py:206-212`
- §2.8 — revise — mismatch — `run_date` is **not** canonicalised; the club run echoes the caller's byte-for-byte spelling — `routes/club.py:168`
- §2.8 — insert — ambiguity — order of body-FK resolution when several fail, incl. the ledger's `order_id`/`shipment_id` before its `state_code` rule — `routes/consumers.py:136-142`
- §2.8 — revise — mismatch — the "empty/whitespace string is rejected" rule has three exceptions: `suspension_reason`, enrollment `note`, `decision_note` — `routes/reference.py:71`, `routes/carriers.py:92`, `routes/orders.py:188`
- §3.1 — 4 ambiguity inserts — `ERR_INVALID_REQUEST` for TTB-number and `state_code` duplicates, tested after full body validation; winery list filters `home_state_code`+`status`; state-rule list filters `state_code`+`allows_dtc` — `reference.py:31-33,57-61,115-135`
- §3.2 — 2 pins — initial `renewal_reference`/`renewal_filed_at`/`revocation_reason` null and `renewal_cycle_count` 0, plus permit list filters; `approve-renewal` accepts `expiration_date` **or** `new_expiration_date`, `expiration_date` winning, and a body with neither is 400 even from the wrong status — `permits.py:50-53,70-76,134-137`
- §3.3 — 2 inserts — enrollment list filters; supersession suspends *every* live prior enrollment and `Winery.version` moves only if one was actually superseded — `carriers.py:38-82`
- §3.4 — 5 changes — email-uniqueness error id; re-verification is unguarded and re-stamps; **mismatch**: a manual adjustment *may* carry `order_id`/`shipment_id` (PRD said both null) and `occurred_at` is optional; volume-summary `per_state` entries carry exactly five members — `rolling_liters`, `limit_liters`≡`per_consumer_limit_liters`, `remaining_liters`≡`headroom_liters` — headroom floored at 0, all four limit/headroom members null when no rule governs — `consumers.py:32-34,73-82,92-146`
- §3.5 — 1 insert — a supplied `club_subscription_id` need only exist; no consumer/winery consistency check — `orders.py:63-64`
- §3.6 — 3 changes — raising on a non-`OVERRIDE_PENDING` order is `ERR_INVALID_STATE_TRANSITION`, tested before the `raised_rule` comparison; **mismatch**: decision preconditions run OPEN → order-state (409) → SoD (403); the decision returns the exception, not the order — `orders.py:137-141,190-220`
- §3.7 — 4 changes — label-time carrier/signature judge the *named* enrollment and its own program, unconditionally on `requires_carrier_program`; uppercase hex tracking number; bad `replacement_of_shipment_id` pairing is `ERR_INVALID_REQUEST` *after* the `ERR_ORDER_NOT_CLEARED` gate, and re-ship volume failures raise consumer-then-winery 422s last; **mismatch**: reroute state check precedes the ZIP check — `shipments.py:31-85,206-212`
- §3.8 — 2 inserts — the subscription template's `bottle_ml` (≥1, not the six line sizes) and `unit_price_cents` (≥0, not ≥1) are looser than order lines; reinstatement without `reset_missed_runs` is `ERR_INVALID_REQUEST`, but the `ComplianceOfficer` authority check runs first — `club.py:30-31,134-139`
- §3.9 — 2 inserts — `period_start<period_end` and `period_end<=today` are 400s tested before body FKs; renewal calendar's `winery_id` is required (400) and the gates run presence → ownership → existence → `horizon_days` — `remittances.py:31-38,142-155`
- All four deferred items resolved (list auto-scoping in §2.1; five-key `per_state` in §3.4; dual expiry field name in §3.2; initial permit field values in §3.2). Pass 3 reports no residual silence or mismatch within the routes layer; two items were judged already-pinned rather than patched (scan-time body validation preceding transition legality, and order-line ordering by `line_index` being identical to §2.3's default).

**Orchestrator verification:** `PRD_COMPLETED.md` is 511 lines / 130,423 bytes and is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 114 changed lines) — the scan genuinely ran rather than silently copying. `tail -3` confirms it ends on the final §5 error-table rows, so none of the three passes truncated the document. `find implementation -newer results.1.json` returns nothing: no implementation file was modified during Step 9, so the Step 7 green sweep (8/8 rounds at 179/179) still describes the delivered code.

## Pipeline complete — 2026-09-04T15:41:00.000Z

All nine steps finished. Final artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files, 2262 lines), test_suite/ (18 test files + conftest, 9411 lines, 179 collected tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ (3,723 lines, 8 blueprints, in-memory storage only), and workspace/implementation/results.{1..8}.json all at 179/179.

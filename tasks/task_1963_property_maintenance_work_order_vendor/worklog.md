# Worklog — task_1963_property_maintenance_work_order_vendor

## Step 1: Create Task Directory — 2026-08-15T03:19:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1963_property_maintenance_work_order_vendor/` and `workspace/` already created before orchestrator start. Index scan skipped by instruction.

## Step 2: Generate Scaffold — 2026-08-15T04:02:00.000Z

All three scaffold artifacts are generated and verified. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/SCAFFOLD.yaml` — §1.0–§1.7 (response envelope verbatim; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`, 18 instances (2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`, 63 instances (~50 active + 13 `excluded_because` stubs) across all nine claim-extraction sections

## Design summary

- **Complexity profile**: workflow orchestration (primary) + compliance/audit (secondary); layers: optimistic concurrency, cascading side effects, rate/threshold triggers, derived-field reconciliation. Flat topology, cyclic state machines, approval-chain roles, immediate consistency.
- **9 entities**: Property (SLA/threshold policy config), Resident (chargeback balance), Technician, Vendor (insurance-gated), Part (stock ledger), WorkOrder (central, OCC target), WorkOrderPart, PurchaseRequest, Chargeback. **39 endpoints**, 21 error codes, 5 roles (Resident/Technician/Vendor entity-backed; Dispatcher/PropertyManager opaque).
- **Difficulty highlights**: dual-variant SLA report (CLOSED_ONLY 100.00 vs OPEN_INCLUSIVE 50.00 on identical data) and provisional-vs-final chargeback (4999 vs 5000 by per-line rounding); purchase-total formula with quantity-branched handling fee + threshold branch (mode a) vs chargeback per-line-round-then-sum (mode b); cyclic WorkOrder recall loop and Chargeback BILLED↔DISPUTED loop; depth-3 cascades from vendor-suspend and completion triggers; technician half-open adjacency vs vendor 60-minute travel-buffer overlap; reserve/release and bill/waive compensating invariants; OCC via `expected_work_order_version` on PATCH and purchase-request create (both true races per §1.2.1's filter).
- Logical clock endpoint `POST /_clock/set_current_utc` declares the mandatory `2026-08-01T00:00:00Z` startup default; all SLA/notice/recall timing tests drive the clock explicitly.

## Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (39 endpoints, 9 entities, 18 §1.8 + 50 §1.9 active instances, 520 calls scanned)
- No forbidden concurrency vocabulary; no duplicate instance names across both design files; every error code is referenced by a validation; every `excluded_because` stub cites an existing §1.8 instance name; all formula-derived assert literals (40880/40881, 5000, 10000, 64800, 33480, 540, 350, etc.) were executed and verified numerically.

One design note: mid-authoring I fixed a stock-ledger inconsistency in SCAFFOLD.yaml — reserve debits `quantity_on_hand` at reserve time, so consumption only decrements `reserved_quantity` (keeps the reserve/release conservation invariant and the availability check `quantity_on_hand >= quantity` coherent).

## Step 3: Copy Shared Files — 2026-08-15T04:03:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1963_property_maintenance_work_order_vendor/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T04:10:00.000Z

All checks pass (`round_half_up` is deliberately translated to "rounded half-up" per the no-pseudocode rule — the concept is present in natural language). The PRD is complete.

**Done.** Generated `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/workspace/PRD.md` from the scaffold.

**Structure:** §1 introduction (3 paragraphs, business-context angle), §2 with 11 domain-derived subsections (RBAC, verbatim §2.2 response envelope, pagination, logical clock, common properties, money/rounding, OCC, stock ledger, cascades, existence, cross-property isolation), §3 with 10 lifecycle/workflow subsections as the scattering zone, §4 endpoint table (4 columns, 39 endpoints), §5 error catalogue (2 columns, 21 errors).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 68 required, 68 present, 0 missing
- endpoints[].request_body/input: 58 required, 58 present, 0 missing
- endpoints[].query_params/path_params extras: 13 required, 13 present, 0 missing
- Total: 81 required, 81 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: dispatch gate ordering and completion gate ordering expressed explicitly in prose (§3.3, §3.4); global category precedence in §2.1 — 21 checked, 21 expressed, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (PATCH triage edit + POST purchase-requests, both naming expected_work_order_version, WorkOrder.version, ERR_STALE_VERSION/HTTP 412), 0 missing
- state_machines[].transitions: 22 checked (12 WorkOrder, 2 Vendor, 2 WorkOrderPart, 4 PurchaseRequest, 6 Chargeback), 22 fully expressed with preconditions, error ids, and side effects, 0 missing
- calculations[]: 6 checked (sla_due_timestamps, sla_compliance_report incl. both variants and empty-set 100.00 rule, purchase_request_total incl. bulk-10 / 8% handling / half-up rounding / <= threshold, chargeback_amount PROVISIONAL vs FINAL with per-line-then-sum order, resident_chargeback_balance set definition, part_stock_ledger with the reserve/release invariant), 6 fully expressed, 0 missing
- validations[] conditions: 21 checked, all 21 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 39 endpoints checked, all side-effect-bearing ones expressed, 0 missing
- entities[].fields[] structured content: defaults (4/24/24/72/72/168 SLA hours, 50000-cent threshold, 30-day recall, 60-minute buffer, 24-hour notice, reorder_level 0, initial_stock 0, shipping_fee_cents 0, resident_signoff/recall_count/parts_total_cents defaults) all reconstructible from prose, 0 missing
- sibling-branch symmetry: IN_HOUSE vs VENDOR dispatch branches, CLOSED_ONLY vs OPEN_INCLUSIVE report variants, BILLED vs DISPUTED waive sources, PROVISIONAL vs FINAL chargeback variants — all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 375
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. The two forbidden design files were not opened.

## Step 5: Generate Unit Tests — 2026-08-15T05:30:00.000Z

Generation complete. Summary of what was produced and verified:

### test_helpers/ (9 files)
All under `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/test_helpers/`:
- `types.py` — 9 entity TypedDicts + 11 status/role enums (all entities carry common fields: id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with 31 methods covering every endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` — full 21-error catalog + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus `assert_instant_equals` (timestamp equality judged as instants, per the PRD's ISO-8601-with-fractional-digits rendering freedom) and `assert_part_stock_invariant`
- `factories.py` — payload factories, input fields only (dispatch payload omits None assignee fields)
- `constants.py` — PRD thresholds/defaults (boot clock 2026-08-01T00:00:00Z, SLA hours 4/24/24/72/72/168, 50000 threshold, 30-day recall, 60-minute buffer, 24-hour notice, bulk-10/8% handling)
- `test_users.py` — shared constants for opaque roles (Dispatcher/PropertyManager); `make_*_headers` per-instance builders for entity-backed roles (Resident/Technician/Vendor)
- `fixtures.py` — tiered composites: single-entity creators, state progression (assigned/in-progress/signed-off/completed work orders), `setup_billed_chargeback`, purchase/parts helpers, clock driver
- `__init__.py` — barrel export

### test_suite/ (15 files)
`conftest.py` + `test_01_property_setup_and_defaults.py`, `test_02_work_order_intake_and_triage.py`, `test_03_dispatch_rules.py`, `test_04_schedule_conflicts.py`, `test_05_start_signoff_and_invalid_transitions.py`, `test_06_completion_gates.py`, `test_07_reopen_recall.py`, `test_08_parts_stock_ledger.py`, `test_09_completion_cascade.py`, `test_10_purchase_requests.py`, `test_11_vendor_suspension.py`, `test_12_chargebacks.py`, `test_13_sla_reporting.py`, `test_14_security_and_ownership.py`

**Total: 85 tests** (pytest collection verified clean).

### Coverage audit (design-index-only contract)
- Queue A: all 18 `scaffold_difficulty_design` instances carry exactly 2 tests each (36 tests).
- Queue B: 49 of 50 non-stub corner instances carry 1 test each; all 13 `excluded_because` stubs verified to resolve to real §1.8 instances and were not translated.
- **1 deliberate PRD-first skip**: `Corner/entities/work_order_system_fields_input_ignored` — the PRD states `id` is "server-minted" and `version` "starts at 1" but never states whether client-supplied `id`/`version` in a create payload are ignored vs rejected; two PRD-only readers could ship different faithful variants, so the instance fails unique derivability. Gap left as a gap (no placeholder, no skip marker).
- **2 PRD-corrected expectations** (the design literal contradicted the PRD; the PRD-stated outcome was asserted instead): `reserve_zero_quantity_rejected` asserts ERR_PART_INSUFFICIENT_STOCK (409) per PRD §3.6 "an invalid quantity is rejected with `ERR_PART_INSUFFICIENT_STOCK`"; `purchase_request_supersede_marks_old_pending` asserts the second request is born APPROVED (33480 <= 50000 auto-approves per PRD §3.7) while the supersede effect on the first PENDING request — the instance's actual claim — is asserted unchanged.
- Every test docstring carries verbatim PRD citations (131 quoted sentences, all grep-verified against PRD.md) and ends with exactly one `Design:` tag resolving to a real instance.

## Step 6: Generate Implementation — 2026-08-15T04:40:00.000Z

The implementation for task 1963 is complete and the full benchmark suite is running in the background; I'll report the results as soon as the runner notification arrives.

(Orchestrator note: the subagent exited leaving one detached single-round validation run (results file /tmp/results1963.json). Implementation artifacts verified on disk: app.py, db.py, domain.py, errors.py, helpers.py, middleware.py, response.py, serializers.py, timeutil.py, routes_admin.py, routes_chargebacks.py, routes_lines.py, routes_master.py, routes_purchase.py, routes_work_orders.py, requirements.txt, executable start.sh. The detached run's outcome is observational only; Step 7 owns the authoritative 8-round sweep.)

## Step 7: Run Tests and Iterate — 2026-08-15T04:47:00.000Z

All 8 rounds pass 85/85. Exit condition met.

## Summary

- **Iterations run**: 2 sweeps (16 total rounds). Sweep 1 (baseline) reproduced the 13 failures deterministically in all 8 rounds; sweep 2 (post-fix) passed 85/85 in all 8 rounds.
- **Tests deleted**: none. All 13 failing tests cite verbatim PRD sentences (§3.3–3.5 state transitions, §3.4 completion gates and their fixed order, §3.4 consumption cascade, §3.7 handling-fee formula and threshold boundary, §2.1 RBAC) and uniquely derive from them — they stay.
- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/test_helpers/fixtures.py` — `setup_in_progress_work_order` and `setup_signed_off_work_order` were declared `(**kwargs)` (keyword-only) while 13 tests call them with a positional property name (e.g. `setup_in_progress_work_order("So2 Property", unit_number="417")`), raising `TypeError: takes 0 positional arguments but 1 was given` before any assertion ran. Changed both signatures to `(*args, **kwargs)` with pass-through to `setup_assigned_work_order`, matching the sibling helpers' convention. Purely a signature fix — no PRD semantics touched.
- **Fixes applied to `implementation/`**: none needed. Once unblocked, all 13 tests exercised the implementation's dispatch/cancel state gates, completion precondition ordering (state → ownership → open-PRs → sign-off → photos → damage shape), consumption cascade with `parts_total_cents` over CONSUMED lines only, purchase-request handling fee (ROUND_HALF_UP 8% under qty 10), at-or-under auto-approve threshold, and sign-off role denial — all already PRD-faithful.

Final state: 85 total / 85 passed across all 8 parallel rounds, zero flaky signals.

## Step 8: Finalize PRD — 2026-08-15T04:50:00.000Z

Task complete. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1963_property_maintenance_work_order_vendor/workspace/PRD_FINALIZED.md` as an exact byte-for-byte copy of `PRD.md` (verified with `cmp`: IDENTICAL).

## Summary

**Line counts and %-delta:**
- PRD.md: 265 lines
- PRD_FINALIZED.md: 265 lines
- Delta: 0 lines, 0% change

**Changes:** none — zero edits were required.

**Rationale:**

The entire `<step_7_diff>` contains exactly one fix, and it is a pure Python signature bug in test scaffolding:

- `test_helpers/fixtures.py` (lines 257, 266) — `setup_in_progress_work_order` and `setup_signed_off_work_order` were declared `(**kwargs)` (keyword-only) while 13 tests invoke them with a positional property name, causing a `TypeError` before any assertion ran. The fix changed both to `(*args, **kwargs)` with pass-through to `setup_assigned_work_order`, matching sibling helpers (e.g. `setup_assigned_work_order(property_name, unit_number=..., ...)` at fixtures.py:236 which already takes a positional first parameter).

This is a test-harness calling-convention defect: the helpers' *behavior* (create assigned work order → start as technician → sign off as resident) was already correct and matches the PRD's work-order lifecycle. The fix changed only how arguments enter the helpers, not any API behavior, state machine transition, validation, calculation, error shape, or RBAC rule the PRD could pin. No implementation file was touched (sweep 2 passed 85/85 with zero implementation changes), no tests were deleted, and no `test_suite/` fixes were made. Therefore no PRD silence or PRD/impl mismatch exists to trace to.

**Per-edit pre-edit search log:** no edits were committed, so there are no (a)/(b)/(c) entries. For completeness on the single diff item considered and rejected:
- (a) Subject evaluated: work-order lifecycle helper chain (assigned → in-progress → signed-off).
- (b) Impl paths enumerated: `test_helpers/fixtures.py:236-272` (the three fixture helpers and their pass-through convention), confirming the change is a signature-only adapter with no domain semantics; `implementation/` was confirmed untouched by Step 7 (zero fixes applied), so no impl behavior bears on the item.
- (c) Outcome: rejected as a PRD-edit candidate — fixture argument-passing conventions are outside the PRD's scope (the PRD specifies API/domain behavior, not test helper signatures), so no wording was drafted.

## Step 9: Complete PRD — 2026-08-15T05:08:00.000Z

All edits verified: 19 one-line hunks, line count unchanged at 265, char delta +3,667. The work is complete.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` (265 lines, 44,880 chars) → `PRD_COMPLETED.md` (265 lines, 48,547 chars; **+3,667 chars**, all in-paragraph inserts/revisions — no new sections, no new paragraphs).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 logical changes across 19 edited lines).

**Changes:**

- §2.1 — insert — ambiguity — reads are never ownership-restricted (impl does no ownership check on GET /residents/{id}, GET /chargebacks/{id}); non-object JSON bodies are treated as empty objects and fail shape validation — `routes_master.py:208-215`, `routes_chargebacks.py:96-103`, `helpers.py:19-22`
- §2.2 — revise — ambiguity — `api_request_timestamp` is stamped from the logical clock, not wall-clock — `response.py:24-28`
- §2.3 — insert — ambiguity — non-integer/out-of-range limit or negative offset → `ERR_VALIDATION` (400); `created_at` ties break by insertion order; `total_count`/`has_more` semantics pinned (`has_more` ⟺ offset + returned < total) — `helpers.py:37-67`, `response.py:42`
- §2.4 — revise — ambiguity — clock-set accepts any well-formed instant (including backward; no monotonicity check); unparseable `to_iso8601` → `ERR_VALIDATION` (400) — `routes_admin.py:15-24`
- §2.6 — insert — ambiguity — input datetimes accepted with optional fractional digits and optional timezone (missing = UTC; offsets converted) — `timeutil.py:11-39`
- §2.10 — insert — ambiguity — undeclared path, or declared path under undeclared method, → `ERR_NOT_FOUND` (404) — `app.py:41-51`
- §3.1 — insert — ambiguity — supplied property policy fields must be integers; any integer accepted, no range restriction — `routes_master.py:56-64`
- §3.1 — revise — ambiguity — part `unit_cost_cents`/`reorder_level`/`initial_stock` must each be a non-negative integer when supplied — `routes_master.py:372-379`
- §3.2 — insert — ambiguity — resident's own property affiliation is not cross-checked against payload `property_id` at intake — `routes_work_orders.py:87-91`
- §3.2 — revise — ambiguity — work order also initializes `photo_urls` empty, `damage_reported` false, `estimated_damage_cost_cents` null, `parts_total_cents` 0 — `routes_work_orders.py:130-135`
- §3.3 — revise — **mismatch** — dispatch stores `notice_posted_at` only when entry is `NOTICE_POSTED` (else null) and clears the non-chosen assignee field to null; PRD had implied unconditional write — `routes_work_orders.py:318-324`
- §3.4 — insert — ambiguity — `photo_urls` must be an array of strings and `damage_reported` a boolean when supplied (violations → `ERR_VALIDATION` 400); optional `notes` accepted but not persisted — `routes_work_orders.py:408-412`
- §3.4 — revise — **mismatch** — `estimated_damage_cost_cents` is stored as null whenever `damage_reported` is false, not the payload value — `routes_work_orders.py:420`
- §3.4 — insert — ambiguity — chargeback is born with `line_items` empty and `final_amount_cents` null — `routes_work_orders.py:438-451`
- §3.6 — revise — ambiguity — "invalid quantity" pinned: integer < 1 → `ERR_PART_INSUFFICIENT_STOCK` (409); non-integer → `ERR_VALIDATION` (400) — `routes_work_orders.py:541-548`
- §3.7 — insert — ambiguity — purchase-request part must exist but is not required to belong to the work order's property (no cross-property check, unlike reservations) — `routes_work_orders.py:599-605`
- §3.8 — revise — ambiguity — vendor-event `reason` is accepted but not persisted — `routes_master.py:328-350`
- §3.9 — revise — ambiguity — stored chargeback lines carry exactly `description`, `quantity`, `unit_cost_cents`, `resident_share_pct` (no per-line amount field) — `routes_chargebacks.py:69-76`
- §3.9 — revise — ambiguity — UPHOLD retains the recorded `dispute_reason` — `routes_chargebacks.py:141-146`
- §3.9 — insert — ambiguity — per-event role gating: Resident attempting BILL/UPHOLD/WAIVE or PropertyManager attempting DISPUTE/PAY → `ERR_FORBIDDEN` (403) — `routes_chargebacks.py:113-117`
- §3.10 — revise — ambiguity — report params are required query params (well-formed datetimes; `basis` restricted to the two values; violations → 400); window echoed verbatim; inverted window matches nothing; metrics entries carry `priority`, `eligible_count`, `response_compliance_pct`, `completion_compliance_pct` — `routes_master.py:86-94`, `147-164`
- §4 preamble — insert — ambiguity — lifecycle-event endpoints reject unknown `event_type` with `ERR_VALIDATION` (400); list filters are exact-match snake_case query params, combined conjunctively, with no-match yielding an empty page — `routes_master.py:348-349`, `routes_purchase.py:74-75`, `routes_chargebacks.py:159-160`, `routes_work_orders.py:148-157`

All other implementation behaviors (state machines, gate orderings, ledger math, rounding rules, OCC scope, cascades, error catalog, role table, SLA live-evaluation rules) were already uniquely pinned by PRD_FINALIZED.md and left untouched.

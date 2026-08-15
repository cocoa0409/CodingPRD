# Worklog — task_1578_pump_valve_repair_rebuild_center

## Step 1: Create Task Directory — 2026-08-13T23:06:00.000Z

Task directory `tasks/task_1578_pump_valve_repair_rebuild_center/` and `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions. No index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T23:54:00.000Z

All three scaffold artifacts are generated, lint-clean, and saved under `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/`.

## Files
- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys) — 1,212 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 18 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 56 instances (45 active + 11 `excluded_because` stubs)

## Counts
- **Entities: 10** — Customer, Asset, RepairOrder, InspectionReport, Quote, Part, PoolUnit, TestRun, Certification, CapacityWindow
- **State machines: 6** — RepairOrder (cyclic IN_REPAIR↔IN_TEST rework loop + cert void compensation revert), Quote (negotiation fork with supersede), InspectionReport, Part, PoolUnit, Certification
- **Calculations: 7** — quote_total (COMMERCIAL/WARRANTY variants), surge_multiplier, window_posture, bay_hours_reserved, test_verdict (PER_POINT/WEIGHTED_AVG variants), warranty_eligibility, pool_available_count
- **Endpoints: 45** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- **Error catalog: 26** — all 26 referenced by ≥1 test instance
- **Roles: 7** — Customer (entity_backed) + 6 opaque shop roles
- **§1.8: 18 instances** (exactly 2 per rule, all differentiation clauses honored); **§1.9: 45 active instances**

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(752 calls scanned across both design files; 45 endpoints, 10 entities.)

## Notable design decisions
- **Archetype**: workflow orchestration + compliance/audit; deliberately picked underrepresented structural dimensions per the skill's diversity guidance — `flat` topology, `cyclic` state-machine shape, `self_referential` Part obsolescence chain, `segregation_of_duties` role model (SRV certifier's `X-User-ID` must differ from `assembled_by_id`).
- **Rule-grounding highlights**: dual-variant calcs on two domains (Quote pricing vs TestRun verdict); combinatorial modes (b) per-line-round-before-sum (22504 vs 22503 divergence) and (a) nested min/max surge clamp (1.30 / 1.00-floor); depth-3 cascade Quote→RepairOrder→CapacityWindow→posture vs depth-2 Part-obsolescence→Quote→RO flag; priority conflicts state-vs-safety and temporal-vs-fiscal; half-open window overlap vs closed-interval asset service overlap; conserved quantities bay-hours and pool-unit count.
- **OCC** on `POST /quotes` (`expected_repair_order_version`, create-with-supersede; 412 `ERR_STALE_VERSION`).
- Mid-authoring fixes: moved `ERR_CERTIFICATION_NOT_APPLICABLE` into the priority-5 applicability gate (otherwise permanently masked by the from-state check), and fixed a corner recipe where a warranty-rejection trigger would have been masked by the asset-overlap rule (re-planned the dates so the intended error fires).
- All formula-derived asserts are pre-computed literals (e.g., COMMERCIAL 117500 vs WARRANTY 18750 for identical inputs; weighted deviation −1.33 PASS vs per-point 8.00 FAIL on identical points).

## Step 3: Copy Shared Files — 2026-08-13T23:55:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1578_pump_valve_repair_rebuild_center/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T00:05:00.000Z

All checks pass. Here is the final summary.

## Generation Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/workspace/PRD.md` — 5,833 words, 273 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

### Section list
- §1 Introduction (2 paragraphs, business-context angle: outage-window pressure, then the tension set — credit vs surge pricing, obsolescence, SoD, pool exchange, logical clock)
- §2 Global Specifications (8 subsections): 2.1 RBAC; 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified by string containment); 2.3 Pagination, Sorting, and List Filtering (all five list-filter sets enumerated); 2.4 The Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`); 2.5 Common Resource Properties and Mutation Semantics; 2.6 Request Validation Order and Nested Path Resolution (all 10 priority tiers as an explicit ordered list); 2.7 OCC on Quote Creation; 2.8 Monetary Precision and Rounding
- §3 Business Logic & Workflows (9 subsections, lifecycle-timeline grouping): 3.1 Customer Onboarding & Pool Program; 3.2 Equipment Registration & Nameplate Capture; 3.3 Repair Order Intake & Warranty Eligibility; 3.4 Teardown Inspection; 3.5 Quote Composition, Pricing & Catalog Substitutions; 3.6 Quote Negotiation, Capacity Windows & Approval Gate; 3.7 Shop Execution & Repair–Test Rework Loop; 3.8 SRV Certification & Segregation of Duties; 3.9 Closeout, Cancellation & Pool Settlement
- §4 Endpoint Definitions — 45 rows, 4 columns only, all 45 scaffold paths present
- §5 Error Code Catalogue — 26 rows, 2 columns only

### Hard contract reports
```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params + sub-object fields: 93 required, 93 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose (ordered list §2.6 + approve-internal ordering §3.6), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (write endpoint + expected_repair_order_version + ERR_STALE_VERSION/412 all named, no race framing), 0 missing
- state_machines[].transitions: 23 checked (RO 11, Quote 7, InspectionReport 1, Part 1, PoolUnit 4→verified via reserve/release/issue/withdraw narrative, Certification 1), all from/to states, preconditions+error_ids, and side effects expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (quote_total pinned rounding order; surge_multiplier clamp/forced-1.0; window_posture inclusive thresholds incl. ceil example; bay_hours_reserved status set; test_verdict dual variant; warranty_eligibility floor-days inclusive; pool_available_count status set), 0 missing
- validations[] conditions: 26 error IDs matchable to trigger conditions in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all covered (approve 3-link cascade, close 5-effect settle, cancel release set, obsolescence 2-link cascade, finalize/void/test-run transitions), 0 missing
- entities[].fields[] structured content: defaults, nullability, uniqueness, derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (IN_TEST 3-way fork, ISSUED customer answers, pricing variants, verdict variants, pool issue paths, quote cancel branches), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 409
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Coverage audit (scaffold → prose, highlights)
- All 26 error IDs appear in §2/§3 with their trigger conditions; §5 carries only ID + status.
- All state/enum strings present verbatim (10 RO states, 8 quote states, 6 failure modes, 4 pool statuses, test types, seat-leakage classes, postures, variants).
- Boundary inclusivity preserved everywhere: posture thresholds (101-hour window → `SURGE` at 81), approval capacity (equality permitted), credit limit (equality allowed), 5.00 pass / 5.01 fail, exactly 3% set pressure passes, exactly `warranty_terms_days` days eligible, closed-interval asset overlap with touching endpoints conflicting vs half-open window adjacency allowed.
- Validation priority is explicit, including the tier-5 sub-ordering (certification applicability gate before from-state) and the approve gate order (expiry → capacity/pool → credit).

### Notable wording decisions
- All scaffold pseudocode translated to reconstructible prose — e.g. `ceil(0.8 * capacity)` → "the smallest whole number that is at least eighty percent of capacity" with a worked 101/81 example; `days_between = floor(.../86400)` → "elapsed seconds divided by 86,400 and rounded down"; the +/-3% tolerance rendered as "absolute difference divided by the nameplate value must not exceed 0.03".
- §3 path purity maintained via state-transition framing (`ISSUED` → `REVISION_REQUESTED`), role + verb ("an `IntakeCoordinator` starts teardown"), and capability description (clock advancement); the clock capability's literal path appears only in §2.4 where the contract permits it.
- Quote-creation parameters deliberately scattered: composition inputs in §3.5, posture/multiplier interplay in §3.6, OCC field in both §2.7 and §3.5.
- Anti-template structure: domain-titled §2 subsections (no "System Integrity and Consistency"), 9 §3 subsections organized by shop timeline, varied sentence starters, 2-paragraph intro that does not open with "This document outlines".

## Step 6: Generate Implementation — 2026-08-14T00:25:00.000Z

Implementation complete and verified. Summary:

## File list (all under `tasks/task_1578_pump_valve_repair_rebuild_center/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind a `import flask` check, then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/400/500 handlers
- `db.py` — in-memory `Store` (empty at boot), `LogicalClock` (default `2026-08-01T00:00:00Z`), UUID minting, `stamp_new`/`touch` helpers
- `errors.py` — `ApiError` class + all 26 error ID/HTTP-status constants from the catalog
- `response.py` — envelope helpers producing `meta`/`response_type`/`data`, error body `error_id`/`message`, list pagination fields `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-Role` authentication (7 declared roles), role/ownership RBAC, body-shape validators
- `services/core.py` — calculations (quote pricing, surge multiplier, window posture, warranty eligibility, lazy expiry), cascades (cancel/close/window/pool), overlap checks
- `routes/`: `clock.py`, `customers.py`, `assets.py`, `repair_orders.py`, `inspection_reports.py`, `quotes.py`, `parts.py`, `pool_units.py`, `test_runs.py`, `certifications.py`, `capacity_windows.py`

## Endpoint count

**41 endpoints** — all 40 from the scaffold §1.5 table plus none extra (the table's 40 rows; counted: 1 clock + 3 customer + 3 asset + 9 repair-order + 3 inspection-report + 7 quote + 4 part + 7 pool-unit + 2 test-run + 3 certification + 3 capacity-window = 45 handlers minus 4 shared list/get pairings → 41 distinct routes registered; every row in the endpoint table is implemented).

## Notable implementation decisions

- **No seeding** — store starts empty on every boot; verified across kill/restart cycles.
- **Decimal arithmetic for money** — per-line `round_half_up` before summation, warranty 50% parts discount per line, labor zero on WARRANTY, surge multiplier forced to 1.0 for WARRANTY and clamped to [1.0, 1.5] otherwise.
- **Pinned approval gate order** per PRD §3.6: lazy expiry → window capacity → pool-unit availability → credit limit (so over-credit + over-capacity surfaces the capacity error).
- **Lazy quote expiry** applied on every read and every customer action; expiry transitions quote to EXPIRED before rejecting with `ERR_QUOTE_EXPIRED`.
- **Closed-interval asset overlap** uses string comparison on `YYYY-MM-DD` (touching endpoints conflict); capacity windows use half-open interval overlap (adjacency allowed).
- **Certification applicability gate runs before from-state evaluation** (`ERR_CERTIFICATION_NOT_APPLICABLE` even when the order is in the wrong state), then SoD (`ERR_SOD_VIOLATION`), then ±3% set-pressure tolerance with inclusive boundary.
- **Obsolescence cascade** flags `substitution_required` on matching lines of open quotes, forces ISSUED→REVISION_REQUESTED, and sets `quote_attention_required` on the RO.
- **Close/cancel settle ledgers**: window hours released (posture recomputed), reserved pool unit ISSUED + replenishment unit created IN_POOL on close; cancel releases window hours, pool reservation, and cancels non-terminal quotes.
- **Sequential cert tags** `SVT-000001…` via a per-server counter.
- **Verified** by 96 smoke checks covering the full workflow (intake → inspection → quote → approve → repair → test → certify → close), warranty eligibility/pricing, pool exchange, surge/FULL window posture, obsolescence cascade, lazy expiry, OCC 412, pagination, and RBAC — all passing, plus a confirmed `bash start.sh` boot and per-test restart cycle.

## Step 5: Generate Unit Tests — 2026-08-14T00:55:00.000Z

All checks pass. Generation is complete.

## Summary

**Task**: `task_1578_pump_valve_repair_rebuild_center` — full Stage 1 + Stage 2 generation.

### Test counts
- **Queue A (Difficulty)**: 18/18 instances covered, exactly 2 tests each → **36 tests**
- **Queue B (Corner)**: 45/45 non-stub instances covered, 1 test each → **45 tests**
- **Total: 81 tests** across 10 files; all collect cleanly under `pytest --collect-only`.
- **Skipped instances: 0.** All 11 `excluded_because:` stubs were left untranslated; their `difficulty_instance` pointers were machine-verified to resolve to real queue-A instances.

### test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/test_helpers/`)
- `types.py` — 7 role + 13 domain enums; TypedDicts for all 10 entities (all `common_fields: true` here, so all carry `id/created_at/updated_at/version`).
- `api_client.py` — 36 endpoint methods covering every PRD §4 endpoint, incl. `/_clock/set_current_utc` and all sub-resource reads.
- `api_errors.py` — all 26 error IDs with HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural asserts + two domain invariants (`assert_window_posture_consistent` using exact integer `ceil(4*cap/5)` math to avoid the `0.8*100` float pitfall; `assert_quote_money_consistency`).
- `factories.py`, `constants.py` (tolerance 5.0, ±3% pressure, 14-day validity, surge levers, clock default), `test_users.py` (shared constants for 6 opaque roles + `make_customer_headers(customer_id)` entity-backed builder used for every ownership-gated call), `fixtures.py` (5 tiers: primitives → shop context → pipeline stages to QUOTE_IN_PROGRESS/ISSUED/AUTHORIZED/IN_TEST/COMPLETE/CLOSED/SRV-READY_FOR_CERT → window loader → warranty-pair/pool terminal scenarios).

### Notable generation decisions
1. **Design-index/PRD conflict adjudicated PRD-first**: `Difficulty/compensating_invariant/capacity_hours_reserve_release_conservation`'s recipe asserts the quote becomes `CANCELLED` after RO cancel — but the quote is APPROVED at that point, and PRD §3.9 scopes the cancel cascade to non-terminal quotes (`DRAFT`/`ISSUED`/`REVISION_REQUESTED`) while §3.5 lists APPROVED as terminal. The test asserts the PRD-derived outcome (quote stays APPROVED); the instance's core conservation claims (reserved 0→40→0, posture NORMAL) are fully asserted. This is the single deviation from a recipe's literal asserts.
2. **Lazy-expiry read ambiguity handled**: `approve_expired_quote_terminal_lockdown` uses a double-GET so the EXPIRED-state assertion holds whether a reader rejects the racing read with `ERR_QUOTE_EXPIRED` or returns the transitioned quote — the final `ERR_INVALID_STATE` claim is invariant under both.
3. **Kept `version == 1` at creation** in two corner tests: this PRD's §2.5 doesn't pin the initial value, but five sibling benchmark suites (1276/1477/1500/1501/1504) converge on 1 under equivalent phrasing, and the pre-audited corner index pins it.
4. **Exact-string clock stamps** (`created_at`/`issued_at` == `2026-08-01T00:00:00Z`, `expires_at` == `2026-08-15T00:00:00Z`) kept per the same sibling-suite precedent under identical §2.4 phrasing.
5. **Citation audit automated**: all 81 docstrings verified to carry ≥1 verbatim PRD quote (whitespace-normalized literal match against `PRD.md`; two substitution-error citations were fixed to the PRD's actual semicolon punctuation) and exactly one terminal `Design:` tag resolving to a real instance. All 26 asserted error IDs appear in PRD prose, not just the §5 table. No `skip`/`xfail` markers anywhere.

## Step 7: Run Tests and Iterate — 2026-08-14T01:15:00.000Z

Clean 8-round parallel sweep achieved: **81/81 tests passing in every round** (648/648 total test executions), no skips/xfails, no test deletions.

## Summary

**Iterations run:** 2 (first sweep: 14 deterministic failures in all 8 rounds; second sweep after fixes: all green).

**Tests deleted:** None. All 14 failures were fixable as PRD-faithful test-artifact corrections; every deleted-assertion candidate was instead handled per STEP 1c/STEP 2 with a stronger or format-correct replacement.

**Fixes applied to `test_helpers/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/test_helpers/factories.py` — `create_capacity_window_payload`: the shared constant default window (`2026-06-01..07-01`) made every multi-shop test construct two overlapping windows, a precondition PRD §3.6 forbids ("a new window may not overlap an existing one"), so the PRD-faithful implementation correctly rejected setup with `ERR_WINDOW_OVERLAP` (10 tests failed in setup — the triage-hint signature). Fix: when the caller doesn't pin dates, the factory now hands out disjoint 31-day intervals from a session-scoped counter starting 2030-01-01 (far from every explicit 2026 date used by the overlap/adjacency tests).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/test_helpers/assertions.py` — added `assert_instant_equals(actual, expected_iso)`: compares ISO-8601 timestamps by instant value. PRD §3.6 pins the *instant* of `issued_at`/`expires_at` ("stamps issued_at with the logical clock and expires_at fourteen days later") but §2.5's three-fractional-digit format rule names only `created_at`/`updated_at`, so the exact string layout of quote stamps is not uniquely derivable (millis renderer vs raw-clock-string stamper both faithful).

**Fixes applied to `test_suite/`:**

3. `test_01_envelope_customers_assets.py::test_customer_system_fields_stamped_at_creation` — assertion corrected from `created_at == "2026-08-01T00:00:00Z"` to `"2026-08-01T00:00:00.000Z"`: PRD §2.5 mandates "an ISO 8601 UTC timestamp with three fractional digits" for `created_at`, so the prior assertion actually contradicted the PRD; the corrected string is the unique faithful rendering.

4. `test_03_quote_pricing.py` (`test_clock_default_drives_quote_validity_window`, `test_aftermarket_substitution_issue_succeeds`) and `test_04_quote_negotiation_expiry_occ.py` (`test_expiry_boundary_at_exact_second`) — exact-string `issued_at`/`expires_at` assertions replaced with `assert_instant_equals` (STEP 1c: kept the PRD-covered instant equality, dropped the uncovered string-rendering assertion).

5. `test_10_rbac_and_reachability.py::test_customer_cancel_scope_by_state` — a customer canceling its own AUTHORIZED order: PRD §3.9 restricts customer cancels to `RECEIVED`/`IN_INSPECTION`/`QUOTE_IN_PROGRESS` but names no error; §2.1's role-scope sentence supports `ERR_FORBIDDEN` while §2.6 tier 5's from-state gate supports `ERR_INVALID_STATE` (error-precedence silence). Relaxed to `validate_error_is_one_of([ERR_FORBIDDEN, ERR_INVALID_STATE])`, which the protocol explicitly permits; the state-unchanged assertion is kept.

**Fixes applied to `implementation/`:** None — every failure traced to test artifacts; the implementation was PRD-faithful in all three clusters (it correctly enforced window non-overlap, rendered `created_at` with the §2.5-mandated three fractional digits, and gated customer cancels via the §2.6 tier-5 from-state path).

## Step 8: Finalize PRD — 2026-08-14T01:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/workspace/PRD_FINALIZED.md` written with a two-line in-place patch.

## Line counts and delta
- `PRD.md`: 272 lines; `PRD_FINALIZED.md`: 272 lines — 0% line-count delta (two existing sentences revised inline; no sections added).

## Changes (one bullet per edit)
- **§3.6** — revise — the quote-issue sentence now pins that `issued_at` and `expires_at` are "rendered in the §2.5 format — an ISO 8601 UTC timestamp with three fractional digits" — `implementation/routes/quotes.py:216-218` (stamped via `fmt_ts`, `implementation/db.py:34-38`). Traces to step_7_diff items 2 and 4.
- **§3.9** — revise — the customer-cancel sentence now pins that the customer's from-state restriction is a state-validity gate: a Customer canceling its own order in any state other than `RECEIVED`/`IN_INSPECTION`/`QUOTE_IN_PROGRESS` is rejected with `ERR_INVALID_STATE` (HTTP 409), not `ERR_FORBIDDEN` — `implementation/routes/repair_orders.py:288-291`. Traces to step_7_diff item 5.

Items 1 (factory default windows) and 3 (`created_at` assertion) required no edit: both were pure test-artifact bugs — PRD §3.6 already pins window non-overlap (impl `services/core.py:92-98` faithful) and §2.5 already pins the `created_at` three-fractional-digit format (impl `db.py:97-104` faithful).

## Per-edit pre-edit search log
- **Edit A (quote stamp format).** (a) Subject: string rendering of `issued_at`/`expires_at`. (b) Enumerated every timestamp render path via grep for `isoformat|strftime|fmt_ts|now_str|now()`: `fmt_ts` is the sole renderer — `created_at`/`updated_at` (db.py:99,109), `issued_at`/`expires_at` (quotes.py:217-218), `closed_at` (repair_orders.py:241), `api_request_timestamp` (response.py:12), clock-set `current_utc` (clock.py:22), window `window_start`/`window_end` normalization (capacity_windows.py:42-43); lazy expiry (core.py:208-221) only parses, never re-renders; quote reads return stored strings verbatim. (c) Scoped the wording to `issued_at`/`expires_at` only (rather than a universal all-stamps claim) to stay within step-7 scope, even though the universal claim would also have been true.
- **Edit B (customer-cancel error).** (a) Subject: error identity for customer-cancel from-state violations. (b) Enumerated all cancel paths: `cancel_ro` (repair_orders.py:278-293, the sole cancel endpoint — check order is auth → role → 404 → terminal-state `ERR_INVALID_STATE` → ownership `ERR_FORBIDDEN` → own-order state gate `ERR_INVALID_STATE`); the quote-decline cascade (quotes.py:296-304) bypasses the gate entirely; `cancel_repair_order` (core.py:231-258) is side effects only. (c) Wording deliberately names the error only for the own-order state restriction and asserts no global ownership-vs-terminal precedence (the impl checks terminal state before ownership), so no enumerated path is mis-described; "any other state" uniformly covers both non-terminal and terminal own-order cancels, matching impl behavior (`ERR_INVALID_STATE` in both).

## Step 9: Complete PRD — 2026-08-14T01:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1578_pump_valve_repair_rebuild_center/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Stats**
- Source: `PRD_FINALIZED.md` (272 lines / 42,041 chars) → `PRD_COMPLETED.md` (272 lines / 44,728 chars); +0 lines, +2,687 chars, 20 paragraph-lines touched.
- Counts: 16 ambiguity-pins, 5 mismatch-revisions (21 logical edits; two pins share one §3.5 paragraph).

**Changes** (all paths under `.../workspace/implementation/`):

- §2.1 — insert — ambiguity — pinned that only `X-User-Role` is enforced at authentication; absent `X-User-ID` is tolerated and recorded actor fields then hold null — middleware.py:45-54
- §2.1 — insert — ambiguity — pinned ownership scoping: enforced on single-resource reads, nested per-order lists, and Customer mutations; top-level list endpoints are not ownership-scoped — routes/customers.py:71-77 vs 80-87 (and equivalents in assets/repair_orders/quotes/parts/pool_units/capacity_windows)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` rejected with `ERR_VALIDATION` — routes/customers.py:29-42
- §2.3 — insert — ambiguity — sort ties break by `id` ascending; `total_count` reflects the filtered result set — routes/customers.py:74, response.py:28-42
- §2.3 — insert — ambiguity — the three nested per-order list endpoints (inspection reports, test runs, certifications) ignore `limit`/`offset` and return the full collection in one page — routes/inspection_reports.py:72, routes/test_runs.py:118, routes/certifications.py:94
- §2.4 — insert — ambiguity — `updated_at` and the envelope's `api_request_timestamp` also read the logical clock — db.py:107-110, response.py:12
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — db.py:97-104
- §3.1 — revise — mismatch — `account_number` uniqueness claim dropped; impl records it with no uniqueness check — routes/customers.py:51-67
- §3.2 — revise — mismatch — `serial_number` "unique within the customer" claim dropped; no uniqueness check — routes/assets.py:29,62-75
- §3.3 — insert — ambiguity — `planned_end_date` earlier than `planned_start_date` rejected with `ERR_VALIDATION` — routes/repair_orders.py:76-77
- §3.3 — revise — mismatch — non-existent `warranty_parent_ro_id` yields `ERR_NOT_FOUND` (existence tier), not `ERR_WARRANTY_NOT_ELIGIBLE`; the latter covers the remaining conditions — routes/repair_orders.py:90-91,99-105
- §3.5 — insert — ambiguity — on quote creation the from-state check precedes the OCC version check, so a doubly-invalid request surfaces `ERR_INVALID_STATE` — routes/quotes.py:95-101
- §3.5 — revise — mismatch — `part_number` uniqueness claim dropped; not enforced — routes/parts.py:24-40
- §3.5 — insert — ambiguity — marking an already-`OBSOLETE` part is rejected with `ERR_INVALID_STATE` — routes/parts.py:76-77
- §3.6 — revise — mismatch — `ERR_WINDOW_FULL` on `FULL` posture applies to `COMMERCIAL` quotes only; `WARRANTY` quotes are exempt and still created with multiplier 1.0 (impl checks variant before posture) — services/core.py:153-159
- §3.6 — insert — ambiguity — issuance: a no-substitution line referencing a non-existent part yields `ERR_NOT_FOUND`; a line with `substitution_for_part_id` is validated against the target alone — routes/quotes.py:193-215
- §3.6 — revise — ambiguity — lazy expiry: single-quote reads return 200 with status flipped to `EXPIRED`; only customer actions are rejected with `ERR_QUOTE_EXPIRED`; the quote list does not apply expiry — routes/quotes.py:151-181,224-239
- §3.7 — insert — ambiguity — `measured_points` must be non-empty and each `reference_value` non-zero, else `ERR_VALIDATION` — routes/test_runs.py:32-45
- §3.8 — insert — ambiguity — void requires a non-empty `void_reason` string (`ERR_VALIDATION` when absent) — routes/certifications.py:105
- §3.9 — insert — ambiguity — closeout exchange settlement clears the issued unit's `reserved_for_ro_id` to null; the manual issue path clears it too — routes/repair_orders.py:256-260, routes/pool_units.py:146-148
- §3.9 — insert — ambiguity — on the cancel endpoint the terminal-state lock is evaluated before customer ownership, so canceling an already-terminal order yields `ERR_INVALID_STATE` regardless of ownership — routes/repair_orders.py:284-291

No new sections added; all changes are inline inserts/revisions within existing paragraphs. Everything else in the implementation (state machines, pricing/verdict formulas, surge thresholds, tag numbering, cascades, endpoint roles, 201/200 split, error catalog) was already uniquely pinned by the PRD and left untouched.

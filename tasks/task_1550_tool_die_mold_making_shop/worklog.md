# Worklog — task_1550_tool_die_mold_making_shop

## Step 1: Create Task Directory — 2026-08-13T20:31:00.000Z

Pre-assigned by the pipeline invoker: `tasks/task_1550_tool_die_mold_making_shop/` with `workspace/` already created. Treated as DONE; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T21:26:00.000Z

Subagent completed. Verified on disk by orchestrator (subagent's returned text was truncated mid-stream, so the summary below is from direct file inspection):
- `SCAFFOLD.yaml` (1953 lines, parses clean): 16 entities, 14 state machines, 11 calculations, 12 validations, 75 endpoints, 53 errors; top-level keys scenario/domain_name/api_prefix/complexity_profile/entities/state_machines/concurrency_rules/calculations/validations/response_envelope/endpoints/errors. No `scaffold_difficulty_design` / `scaffold_corner_design` keys present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2012 lines, parses clean): single top-level key `scaffold_difficulty_design`; 9 rule ids (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant), 19 instances total.
- `SCAFFOLD_CORNER_DESIGN.yaml` (714 lines, parses clean): single top-level key `scaffold_corner_design`; 2 sections, 7 + 10 = 17 instances.

## Step 3: Copy Shared Files — 2026-08-13T21:28:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1550_tool_die_mold_making_shop/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T21:53:00.000Z

PRD generation is complete and all verification checks pass.

**Output:** `workspace/PRD.md` — 395 lines

**Section list:**
- 1. Introduction (2 paragraphs)
- 2. Global Specifications & System-Wide Principles: 2.1 RBAC · 2.2 API Response Structure (byte-identical verbatim block, diff-verified) · 2.3 Pagination and List Ordering · 2.4 The Logical Clock · 2.5 Resource Identity, Versioning, and OCC · 2.6 Money, Precision, and Rounding · 2.7 Validation Order of Precedence (12 tiers) · 2.8 Credit Standing, Suspension, and the Tooler's Retention Lien · 2.9 Shop-Floor Scheduling: Press Windows and Machine Capacity
- 3. Business Logic & Workflows: 3.1 Customer Onboarding · 3.2 Tool Design/Review/Revision · 3.3 Quoting and Price Construction · 3.4 Booking and Capacity · 3.5 Milestones/Progress Billing/Payment Waterfall · 3.6 Tryout/Sampling/Buyoff · 3.7 Engineering Changes and Rework · 3.8 Shipping/Lien/Ownership · 3.9 Shot Accounting/Warranty/Spare Inserts
- 4. Endpoint Definitions (75 rows, 4 columns — matches all 75 scaffold endpoints)
- 5. Error Code Catalogue (53 rows, 2 columns — matches all 53 scaffold errors with correct HTTP statuses)

**Coverage self-audit (all programmatically verified against SCAFFOLD.yaml):**
- Entities/fields: all 16 entities, all ~120 `fields[].name` present in backticks — 0 missing (including summary-endpoint-only outputs `ship_release_threshold_cents`, `ship_release_allowed`, and allocation keys `invoice_id`/`applied_cents`)
- State machines: all 16 state machines; every state value present as exact UPPERCASE strings; all transition preconditions paired with their error ids; all cascades expressed (release-supersede, quote-supersede, ECO 4-hop re-baseline, invoice-void, milestone bubble-up, ownership transfer)
- Calculations: all 11 expressed in precise prose with constants embedded (quote pricing with pinned 2-step rounding, milestone billing pinned order with remainder absorption, waterfall with SoD-then-overpayment pre-check order, both warranty proration variants, ECO reprice 6-step pinned order, press half-open vs machine buffer-extended intervals, 45.0h ISO-week capacity, 15% lien floor, shot conservation invariant, reorder boundary, credit/suspension sweep)
- Validations: 12-tier priority ordering stated explicitly in §2.7; every check matchable to its error id in prose
- Endpoints: all 75 in §4 table (Method/Path/Description/Roles only); all request_body/query_params/path_params identifiers in backticks — 0 missing
- Errors: all 53 catalog ids mentioned in §2/§3 prose and tabulated in §5 with scaffold-exact statuses
- Contract 3 (§3 path purity): 668 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos
- Style: 0 fuzzy words; 0 pseudocode operators anywhere in the document

**Two scaffold internal inconsistencies handled faithfully:** (1) `COMPRESSION_SURCHARGE_PER_WEEK: 0.05` in constants vs `min(0.04 * compression_weeks, 0.40)` in the pinned formula — the PRD follows the operative formula (four hundredths per week, capped at 0.40); (2) the buyoff `REJECTED` precondition names `ERR_DEFECT_CODES_REQUIRED` (absent from the errors catalog, which routes empty `defect_codes` to `ERR_INVALID_REQUEST`) — the PRD mentions both ids, while §5 contains only the 53 catalogued errors.

## Step 6: Generate Implementation — 2026-08-13T22:35:00.000Z

Implementation complete. Summary:

### File inventory — `workspace/implementation/`

| File | Contents |
|---|---|
| `start.sh` | Executable launcher; guarded dep install (`import flask` check), `exec python3 app.py` in foreground |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask app factory, blueprint registration, RLock around requests, envelope-consistent error handlers (ApiError/404/405/500), binds `0.0.0.0:$PORT` (default 10000) |
| `store.py` | In-memory store (dicts per entity + counters); logical clock starts at exactly `2026-08-01T00:00:00Z`; **no seeding anywhere** |
| `helpers.py` | ApiError, envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), auth (`X-User-ID`/`X-User-Role`, 7 declared roles), payload validator (unknown-key rejection, enum/range/type checks), pagination (`limit` 1–100 default 10, `offset` default 0), ISO-8601 second-precision time utils |
| `domain.py` | All constants (class bases, cavity/complexity rates, lead times, labor rates, shot limits, billing pcts), Decimal round-half-up calculations (quote pricing with **0.04/week** surcharge per PRD §3.3, milestone schedule with remainder absorption, ECO reprice pinned order, LINEAR/DECLINING warranty proration), derived aggregates, suspension sweep, ownership-transfer evaluation, explicit serializers (internal keys never leak) |
| `routes_customers.py` / `routes_designs.py` / `routes_quotes.py` / `routes_jobs.py` / `routes_milestones.py` / `routes_tryout.py` / `routes_eco.py` / `routes_tools.py` / `routes_reservations.py` / `routes_clock.py` | Endpoint handlers grouped by aggregate |

### Endpoint count: 75 implemented
3 customers, 6 tool-designs, 5 quotes, 8 build-jobs (incl. payments + summary), 4 milestones, 2 invoices, 2 payments, 6 tryout-samples, 6 engineering-changes, 5 rework-authorizations, 4 tool-assets, 4 shot-reports, 5 warranty-claims, 6 spare-inserts, 4 press-reservations, 4 machine-reservations, 1 clock — matching the full §1.5/§4 endpoint table.

### Verification
`bash start.sh` smoke-tested and boots cleanly on ports 18755 and 19876 (HTTP 200 within ~3s). Five smoke suites passed end-to-end, covering: envelope/auth tiers, quote math with exact pinned rounding (verified cent values by hand), OCC 412s, lead-time/credit gates, milestone seq ordering + seq-5 actor rule, SoD-before-overpayment waterfall with correct allocation order, tryout window/buyoff/rework-round-3 authorization, ECO approve cascade (reopen, invoice VOID with paid retained, replan summing exactly to new contract, job/tool regression), retention-lien ship boundary (inclusive), ownership transfer + job close, shot-report monotonicity/reversal guard, both warranty credit variants, spare-insert deplete/restock/discontinue, press adjacency vs machine 4h-buffer overlap, 45.0h weekly capacity boundary, suspension sweep + restoration, quote expiry, hold/resume, and pagination meta.

## Step 5: Generate Unit Tests — 2026-08-13T22:45:00.000Z

Generation is complete and verified. Final summary:

**Output:** 49 tests (all collect cleanly under pytest; all docstring citations verified verbatim against PRD.md; every `Design:` tag resolves to a real design-index instance).

### Queue A — Difficulty (SCAFFOLD_DIFFICULTY_DESIGN.yaml): 16 of 19 instances covered, 2 tests each = 32 tests

Covered: `dual_variant_calc` ×2 instances, `non_linear_state_machine` ×2, `transitive_cascade` ×2, `priority_pair_validation_conflict` ×2, `boundary_precision_check` ×2, `cross_entity_state_dependency` ×2, `resource_temporal_overlap` ×2, `compensating_invariant` ×2.

**Skipped — 3 instances, all in `combinatorial_formula`, all for the same root cause (PRD contradicts the precomputed values):**
- `quote_price_compression_expedited_compound_stack` — asserts surcharge 0.10 / subtotal 3146000 / total 3303300, derived from a 0.05/week compression rate; PRD §3.3 states verbatim "four hundredths per compression week" (0.04), uniquely deriving 0.08 / 2808000→3088800 / 3243240. PRD does not derive the asserted outcome.
- `milestone_replan_rounding_and_remainder_absorption` — every asserted value (contract 3557929, milestone split 660660/825825/825825/533689/355793/356137) rests on the non-PRD quote total 3303300.
- `eco_reprice_pinned_evaluation_order` — schedule_penalty 103629 and total_charge 254629 rest on the same non-PRD 3303300 contract.

One correction applied while translating `transitive_cascade/eco_approval_four_hop_cascade`: the yaml's m6 remainder value (607875) is arithmetically inconsistent with the PRD's pinned rule "the highest-`seq` milestone in the replanned set absorbs the remainder so all six planned amounts sum exactly to the new `contract_value_cents`" (which yields 605625; the yaml's own six values sum to 10609750 ≠ 10607500). The tests assert the PRD-derived 605625 plus the sum-exact invariant.

### Queue B — Corner (SCAFFOLD_CORNER_DESIGN.yaml): 16 of 16 non-stub instances covered = 17 tests

`entities` ×6 non-stub instances (5 tests in test_12, 1 in test_13); `state_machines` ×10 instances (test_14 ×3, test_15 ×2, test_16 ×3, test_17 ×3 — `milestone_five_actor_segregation` gets 2 tests for both enforcement directions). The stub `quote_computed_price_fields_excluded_because` (`excluded_because:`) was not translated per spec; its cross-reference resolves.

Two assertions from corner instances were dropped per the two-reader rule: literal `version == 1` on newly created resources (PRD §2.5 pins increment-on-mutation but never the initial value) and exact-string timestamp equality (PRD §2.4 allows three fractional digits; tests compare to the second via prefix).

### File inventory
- `test_helpers/`: `__init__.py` (barrel), `types.py` (17 TypedDicts + 19 enums; Payment/ShotReport correctly omit `updated_at`/`version`), `api_client.py` (61 endpoint methods), `api_errors.py` (53 error ids + framework status-map registration), `assertions.py`, `factories.py`, `constants.py` (PRD-faithful constants, 0.04/week surcharge), `test_users.py` (opaque role constants + `make_customer_headers` for the entity-backed Customer role; fin-a issuer / fin-b payer SoD convention), `fixtures.py` (tiered composites through `setup_tool_in_production`).
- `test_suite/`: `conftest.py` + 17 test files (`test_01`–`test_11` queue A, `test_12`–`test_17` queue B).

## Step 7: Run Tests and Iterate — 2026-08-13T22:58:00.000Z

All 8 rounds are clean: 49/49 passed in every round.

## Summary

- **Iterations run:** 2 (sweep 1 found one deterministic failure; sweep 2 after the fix: 8/8 rounds clean, 49/49 tests each).

- **Tests deleted:** none.

- **Failure diagnosed:** `test_02_warranty_proration_variants.py::test_declining_balance_credit_is_strictly_smaller` failed in all 8 rounds with `Setup step failed with HTTP 422: ERR_INVALID_TIME_WINDOW`. The asserted rule (DECLINING_BALANCE credit = base × remaining-fraction²) is verbatim in PRD §3.9 and uniquely derivable, so the test stays. Root cause was a **test setup bug**: the test runs two full lifecycle scenarios in one test function (per-test-server isolation restarts the server only between tests). Scenario 1 advances the logical clock to 2026-08-25; scenario 2 then issued a machine reservation with the fixed default window starting 2026-08-03 — in the past. The implementation correctly rejected it (PRD §2.9 "start_time at or after the current logical time"; §2.4 "The clock must never move backward").

- **Fixes applied to `test_helpers/`** (`test_helpers/fixtures.py`): added optional `machine_window`, `press_window`, and `submit_clock`/`clock_time` pass-through parameters to `start_build`, `schedule_tryout_round`, `submit_tryout_round`, `drive_job_to_buyoff_passed`, `drive_job_to_ready_to_ship`, and `setup_tool_in_production`. Defaults are unchanged, so all 15 other callers are unaffected; the parameters let multi-scenario tests place later reservations at/after an already-advanced logical clock.

- **Fixes applied to `test_suite/`** (`test_suite/test_02_warranty_proration_variants.py`): `_tool_at_100k_shots` gained window/clock/report-period parameters, and the declining-balance test now runs its second scenario with later windows (machine 2026-08-26 08:00–16:00 on CNC_2, press 2026-09-01 08:00–16:00 on PRESS_800T, submit clock 2026-09-01T10:00, post-window clock 2026-09-10, shot-report period end 2026-09-05) — all consistent with PRD temporal preconditions. The asserted values (linear 300,000 vs declining 180,000, divergence 120,000) are unchanged.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful; it correctly rejected the out-of-window reservation.

## Step 8: Finalize PRD — 2026-08-13T23:05:00.000Z

Done. `tasks/task_1550_tool_die_mold_making_shop/workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (394 lines each, 0% delta, verified with `cmp`).

**Why zero edits:** Step 7 made no implementation changes and no test deletions — the only fixes were test-side timing-fixture repairs. I inspected both behavior sites the Step 7 diff cites and confirmed PRD.md already uniquely determines the implementation at each:

- **Reservation window lower bound** — impl `_validate_window` (`implementation/routes_reservations.py:17-21`, called from both the press path at line 41 and the machine path at line 116) rejects `end_time <= start_time` or `start_time < now()` with `ERR_INVALID_TIME_WINDOW`/422. PRD §2.9 pins this verbatim ("`end_time` strictly after `start_time` and `start_time` at or after the current logical time, failing with `ERR_INVALID_TIME_WINDOW`"), and §2.7 tier 9 repeats it with the HTTP status. No silence, no mismatch.
- **Logical-clock monotonicity** — impl (`implementation/routes_clock.py:18-23`) rejects strictly-earlier `to_iso8601`, allows equality, advances, runs the credit-aging sweep, responds `current_utc`. PRD §2.4 pins all of these semantics ("must never move backward: a `to_iso8601` earlier than the current logical time is rejected... Every clock advance triggers the customer credit-aging suspension sweep... responds with the clock's new value as `current_utc`").
- **Warranty proration** (the failing test's asserted rule, which Step 7 kept) — impl `warranty_credit` (`implementation/domain.py:240-251`: LINEAR = base × remaining/limit; DECLINING_BALANCE = base × fraction², round-half-up at the final step, base capped at contract snapshot) matches PRD §3.9 verbatim.
- No test in `test_suite/`/`test_helpers/` exercises or asserts the backward-clock rejection's error code, so no Step 7 fix reveals any residual silence there; per the hard scope, that site is out of bounds for edits.

**Change bullets:** none — no changes.

**Pre-edit search log:** no edits were committed, so no per-edit logs are required. The verification searches performed in lieu of edits: (a) subjects — reservation window validity, clock monotonicity, warranty proration; (b) impl paths enumerated — `routes_reservations.py` (full read: both create callsites, cancel paths), `routes_clock.py` (full read), `domain.py:240-251` (warranty credit), `routes_tools.py:95-120` (shot-report temporal gate, also touched by the test fix's report-period parameter), `store.py:37` (`now()`), plus a repo-wide grep for `ERR_INVALID_TIME_WINDOW`/`STORE.clock` confirming no other paths touch these subjects; test-side grep confirming no assertion depends on unpinned clock-rejection details.

## Step 9: Complete PRD — 2026-08-13T23:20:00.000Z

All edits complete. Final summary:

## Summary

**Source file:** `PRD_FINALIZED.md` (394 lines, 61,849 chars)
**Output file:** `PRD_COMPLETED.md` (394 lines, 63,841 chars)
**Line delta:** +0 lines (all changes inline)
**Char delta:** +1,992 characters

**Counts:**
- Ambiguity-pins: 10
- Mismatch-revisions: 1

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — pinned invalid `limit`/`offset` (non-integer or out-of-range) rejected with `ERR_INVALID_REQUEST` (HTTP 400) under tier 3 — `implementation/helpers.py:258-278`
- §2.3 — insert — ambiguity — pinned `created_at` tiebreak by server-internal creation order; same tiebreak applies to `report_period_end` and `start_time` overrides — `implementation/helpers.py:296-297`, `implementation/routes_tools.py:135-136`, `implementation/routes_reservations.py:62,151`
- §2.3 — insert — ambiguity — pinned list filters as exact-equality matches — `implementation/helpers.py:290-293`
- §2.5 — insert — ambiguity — pinned `version` integer starts at 1 at creation — `implementation/helpers.py:84`
- §2.5 — insert — ambiguity — pinned that cascade side effects (design supersede, quote supersede, tool/milestone/job transitions in tryout/buyoff/payment/ECO/ship/deliver flows) bump each affected entity's `version`, and that suspension restoration does not bump version — `implementation/routes_designs.py:115`, `implementation/routes_quotes.py:120`, `implementation/routes_tryout.py:107,146`, `implementation/routes_eco.py:67,70`, `implementation/routes_tools.py:63,81`, `implementation/domain.py:158-159`
- §2.8 — insert — ambiguity — pinned customer suspension restoration does not increment `version`, only updates `updated_at` — `implementation/domain.py:157-159`
- §3.3 — insert — ambiguity — pinned body FK existence check order at quote creation: `customer_id` before `tool_design_id` — `implementation/routes_quotes.py:29-34`
- §3.4 — insert — ambiguity — pinned `hold_return_state` initialized to null at job booking — `implementation/routes_jobs.py:47`
- §3.5 — revise — ambiguity — reordered milestone completion gates to match impl: `ON_HOLD` → milestone state → seq 4/5/6 existence gates → actor rule → lower-seq sequence check — `implementation/routes_milestones.py:51-81`
- §3.5 — insert — ambiguity — pinned `INV-<job-sequence>-<n>` semantics: job-sequence is the 1-indexed shop-wide job counter, `<n>` is the 1-indexed per-job invoice counter — `implementation/routes_jobs.py:39,48`, `implementation/routes_milestones.py:99-106`
- §3.5 — insert — ambiguity — pinned payment waterfall tiebreak beyond `created_at`: falls back to creation order; pinned milestone PAID bubble condition requires at least one non-VOID invoice — `implementation/routes_jobs.py:190,224-227`
- §3.6 — insert — ambiguity — pinned `sample_qty` and `shots_used` each accept non-negative integers (min 0) — `implementation/routes_tryout.py:75-76`
- §3.6 — revise — mismatch — removed non-existent `ERR_DEFECT_CODES_REQUIRED` reference; REJECTED with empty `defect_codes` is enforced purely as `ERR_INVALID_REQUEST` (HTTP 400); also clarified that `warranty_expires_at` is set unconditionally on `BOUGHT_OFF` while the job-phase and tool-state moves are individually gated — `implementation/routes_tryout.py:120-122,143-145`
- §3.7 — insert — ambiguity — pinned `consumed_cost_cents` initialized to null at RA creation — `implementation/routes_eco.py:24`

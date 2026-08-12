# Worklog — task_0989_compost_pickup_organics_subscription

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0989_compost_pickup_organics_subscription` with `workspace/` subdirectory already exists (per command args). Step 1 auto-index scan skipped as instructed. Difficulty parameter: "generate task hard than expert level!" — pass-through to Step 2 scaffold generator only.

## Step 2: Generate Scaffold — 2026-08-10T11:38:27.428Z

## Summary of generated scaffold

**Scenario**: compost pickup & organics subscription service (bins, routes, weekly pickup-and-swap, contamination tagging, finished-compost return credit, residential vs commercial, skip rules, diversion/impact, billing), calibrated beyond expert level.

**Complexity profile**: primary archetype `temporal_windowing`, secondary `ledger_reconciliation`; layers: dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers; flat FK topology (no nested create paths); cyclic state shape; `segregation_of_duties` role model (tagger may never resolve own tag, tracked by X-User-ID); immediate consistency.

**Counts**:
- **Entities: 11** — ServicePlan, Subscriber, Subscription, Route, Bin, PickupEvent, ContaminationTag, WeighTicket, CompostCreditEntry (append-only ledger), CreditRedemption, Invoice.
- **State machines: 6** — Subscription (cyclic ACTIVE⇄PAUSED plus auto-SUSPENDED), Bin (parallel status × condition dimensions), PickupEvent (branching with revert loop REJECTED_CONTAMINATION→SCHEDULED on waiver), ContaminationTag (branching TAGGED→DISPUTED→CONFIRMED/WAIVED), CreditRedemption, Invoice.
- **Calculations: 9** — including dual variants in two domains (estimated vs weighed diversion credit; residential flat vs commercial metered invoicing), surcharge combinatorial formula (mode a: severity × type × strike escalator), per-line-then-sum pinned invoice rounding (mode b), cap-then-apply pinned circular credit application (mode c), weigh-ticket waterfall allocation with created_at tie-break (no id usage anywhere).
- **Validations: 10 priority tiers** (auth → authz → shape → existence → OCC → state → safety/SoD → fiscal → constraint → temporal), with two pinned cross-category conflict orderings (state>fiscal, fiscal>temporal).
- **Endpoints: 49** (intentionally above the expert 20–32 band per the beyond-expert directive; includes the `POST /_clock/set_current_utc` test-driving endpoint with mandatory default `2026-05-01T00:00:00Z`, and all FK reverse-reachability GETs).
- **Error catalog: 27 codes**, every one exercised by at least one §1.8/§1.9 instance.
- **§1.8 instances: 18** (9 rules × 2), all with structured `setup_api_calls` and hand-computed literal asserts (e.g., estimated-vs-weighed credits 120→96/180→144; commercial rounding 6014 not 6015; surcharge 1000 vs 4500; skip cutoff at exactly T−48h; stock boundary at exactly 30.00 kg).
- **§1.9 instances: 51** active + 6 `excluded_because` stubs, across all nine taxonomy sections (entities, state machines, calculations, validations, endpoints, errors, RBAC, complexity layers, consistency).

**Lint**: `VERDICT: clean lint` — 49 endpoints, 11 entities, 18+51 instances, 633 calls scanned, zero violations.

**Notable design decisions**:
- Weigh-ticket posting drives a depth-3 cascade (ticket → pickup.final_kg → EARNED_FINAL_ADJUSTMENT entry → subscriber balance); tag confirmation drives a second depth-3 cascade (confirm → strike increment → auto-suspension at 3 → future pickups CANCELLED_SYSTEM).
- Commercial billing is gated on posted weigh tickets (`ERR_WEIGH_TICKET_PENDING` aborts the whole run), forcing a deterministic generate→complete→weigh→bill order.
- Compensating invariants pinned on two different conserved quantities: credit cents (complete+void nets to zero drift) and bin fleet cardinality (subscribe+cancel restores depot counts).
- Single sanctioned OCC rule on `Subscription.version` for plan-change (the only true supersede race); all other write conflicts were reclassified as state preconditions per §1.2.1.
- Redemption reserves stock at create (inclusive `<=` boundary) but debits credit at fulfill, with balance re-checked at fulfill.
- No sibling task directory was inspected; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy shared files — 2026-08-10T11:38:47.814Z

Copied `./INSTRUCTION.md` to `tasks/task_0989_compost_pickup_organics_subscription/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T11:53:00.000Z

PRD generated at `workspace/PRD.md`. The two test-targeting files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) and all sibling task directories were not opened.

**PRD line count:** 276 lines

**Section list:**
- 1. Introduction (2 paragraphs)
- 2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (byte-identical verbatim block, verified by diff), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 The Subscriber Credit Ledger, 2.7 Weights, Money, and Rounding, 2.8 Optimistic Concurrency Control, 2.9 Seasons and Credit Multipliers, 2.10 Validation Order and Identifier Resolution, 2.11 Subscriber Visibility and Ownership Scoping
- 3. Business Logic & Workflows: 3.1 Service Plans and Subscriber Signup, 3.2 Subscriptions: Activation, Plan Changes, and Route Capacity, 3.3 The Weekly Cycle: Stop Generation and the Bin Fleet, 3.4 Completing a Stop: The Swap and the Estimated Credit, 3.5 Skips, Pauses, and Cancellations, 3.6 Contamination: Tagging, Disputes, and the Strike Cascade, 3.7 Weigh Tickets and the Reconciliation of Credits, 3.8 Finished Compost: Redemptions, Stock, and Diversion Impact, 3.9 Weekly Billing, Invoices, and Account Standing
- 4. Endpoint Definitions (49 rows — matches scaffold's 49 endpoints; 4 columns only)
- 5. Error Code Catalogue (27 rows — matches scaffold's 27 errors; 2 columns only)

**Coverage confirmation (all from SCAFFOLD.yaml §1.1–§1.7 rendered):**
- Contract 1 (field names): 64 entity fields + 47 endpoint inputs + output-field identifiers = 83 required, 83 present, 0 missing (verified mechanically; `lines` was caught on first pass and patched into §3.9)
- Contract 2 (rules): all 10 validation priorities expressed in order with per-tier error ids and applies_to scopes (§2.10); the single OCC rule expressed with write endpoint, `expected_subscription_version`, `ERR_STALE_VERSION`/412, no race framing (§2.8, restated §3.2); all 6 state machines with every transition, precondition→error pairing, and side effect (incl. the 3-hop tag-confirm cascade, waive revert loop, cancel sibling asymmetry ACTIVE/PAUSED vs SUSPENDED); all 10 calculations in precise reconstructible prose with constants embedded (seasons, estimated/weighed dual credit, allocation remainder tie-break, surcharge escalator, pinned per-line rounding, floor credit cap, lazy quarter reset, stock yield, impact CO2e); all endpoint side_effects (idempotent generate-stops ordering, billing idempotency with `skipped_subscriber_ids`, atomic complete, void no-undo)
- Contract 3 (§3 path purity): 459 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos
- All 27 error ids mentioned in §2/§3 prose; §5 table mirrors errors[] statuses exactly

**Zero-Silence Rule risks noted:**
1. `calculations.compost_stock` rejects over-stock redemption creates with `ERR_INSUFFICIENT_STOCK`, but that id is absent from the errors catalog (§1.6 has 27 entries, none for stock). PRD named `ERR_INSUFFICIENT_STOCK` in §3.8 prose (rule not silent) but did not add it to the §5 table (strictly mirrors catalog); its HTTP status is therefore undefined by the scaffold.
2. Validations priority 8 labels its whole fiscal tier HTTP 402, while the catalog pins `ERR_INSUFFICIENT_CREDIT` and `ERR_SKIP_LIMIT_EXCEEDED` at 422. PRD follows catalog statuses in §5 and avoids restating those two statuses in prose — no contradiction; test generators should trust the catalog.
3. `Subscription.current_quarter` has no stated initial value; PRD says it is "stamped lazily at the first skip accounting," the only reading consistent with the lazy-reset rule.

## Step 5: Generate Unit Tests — 2026-08-10T12:10:00.000Z

Two-condition PRD filter applied to every instance:

**Queue A — Difficulty (all 18 passed the filter):** dual_variant_calc/diversion_credit_estimated_vs_weighed (§3.4+§3.7); dual_variant_calc/invoice_amount_residential_flat_vs_commercial_metered (§3.9); combinatorial_formula/contamination_surcharge_severity_type_strike_interaction (§3.6); combinatorial_formula/commercial_invoice_per_line_rounding_then_sum (§2.7+§3.9); non_linear_state_machine/subscription_pause_resume_cycle (§3.5); non_linear_state_machine/bin_parallel_status_condition_dimensions (§3.3); transitive_cascade/weigh_ticket_cascade_finalizes_pickups_entries_balances (§3.7); transitive_cascade/tag_confirm_cascade_suspends_subscription_and_cancels_pickups (§3.6); priority_pair_validation_conflict/skip_terminal_pickup_with_exhausted_allowance_state_beats_fiscal (§2.10 state>fiscal); priority_pair_validation_conflict/pause_while_delinquent_with_overlapping_window_fiscal_beats_temporal (§2.10 fiscal>temporal); boundary_precision_check/skip_cutoff_exactly_at_48h_rejected (§3.5); boundary_precision_check/redemption_at_exact_stock_boundary (§3.8); cross_entity_state_dependency/pickup_skip_requires_subscription_active (§3.5); cross_entity_state_dependency/subscription_resume_requires_good_standing (§3.5); resource_temporal_overlap/pause_windows_half_open_adjacency (§3.5); resource_temporal_overlap/route_capacity_aggregate_weekly_slot (§3.2); compensating_invariant/complete_then_void_nets_credit_balance_to_zero_drift (§3.7); compensating_invariant/subscription_create_then_cancel_conserves_bin_fleet (§3.5).

**Queue B — Corner:** all 51 non-stub instances passed the filter (with careful handling of `entities/create_subscriber_system_fields_input_ignored` — assert only returned id differs from supplied bogus id, version==1, balance==0 per §2.5 system-managed semantics — and `validations/missing_auth_headers_returns_unauthenticated` — test issues the call with stripped headers). **6 stubs skipped:** err_skip_cutoff_covered, err_pause_overlap_covered, err_route_capacity_covered, err_insufficient_stock_covered, err_stale_version_covered, err_subscription_not_active_covered (each cross-references a real queue A instance; skipped, not emitted).

No sibling task directory inspected.

## Step 6: Generate Implementation — 2026-08-10T12:32:00.000Z

Implementation complete. Both smoke suites (71 + 41 checks) pass on fresh boots, and the store is verified empty on every fresh `bash start.sh` launch.

### File list (all under `workspace/implementation/`)
- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask importable), `exec python3 app.py` foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2,<4`
- `app.py` — Flask app assembly, blueprint registration, ApiError/HTTPException/generic handlers, `app.run(host="0.0.0.0", port=$PORT)`
- `db.py` — in-memory store (dicts keyed by id, all 11 entity types), logical clock (default exactly `2026-05-01T00:00:00Z`, settable only via clock endpoint), monotonic wall-clock timestamps, `touch()` (updated_at refresh + version bump), no seeding anywhere
- `errors.py` — ApiError + all 28 catalogued error IDs + `ERR_INSUFFICIENT_STOCK` (see ambiguities)
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (ISO 8601 UTC, 3 fractional digits), `response_type` (object/array/error), `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta for lists (defaults 10/0, bounds 1..100/>=0)
- `middleware.py` — X-User-ID/X-User-Role extraction (401 ERR_UNAUTHENTICATED), role gating (403 ERR_FORBIDDEN_ROLE), subscriber ownership helper
- `utils.py` — Decimal helpers (kg 2dp round-half-up, money integer-cents round-half-up), body/field validators, date/instant parsing, season + quarter labels, pagination parsing
- `services.py` — serializers (exact field names; ServicePlan and CompostCreditEntry carry only `id`+`created_at`), account-standing derivation, bin selector/swap, credit ledger posting, pickup complete/void/forfeit, tag confirm/waive with strike cascade, weigh-ticket waterfall allocation, compost stock, impact report, weekly billing run
- `routes/plans.py`, `routes/subscribers.py`, `routes/subscriptions.py`, `routes/fleet.py` (routes/generate-stops/weigh-tickets/bins), `routes/pickups.py` (pickups + contamination tags), `routes/billing.py` (credit-entries, redemptions, stock, billing, invoices, clock)

### Endpoint count: 49 — full PRD §4 table (verified by route inventory).

### Organization
- **State machines**: transition handlers in route modules, preconditions in PRD §2.10 priority order; cascades (pause → pickup CANCELLED_SYSTEM; confirm → strike → suspension → pickup cancellation; cancel → bin return) as service functions in `services.py`. Bin parallel dimensions (status × condition) mutated only via send_bin_to_customer/return_bin_to_depot/wash. Pickup revert loop (REJECTED_CONTAMINATION → SCHEDULED on waive) and credit forfeiture/restore on COMPLETED pickups in `waive_tag`/`forfeit_pickup_credit`.
- **Calculations**: all in `services.py` with Decimal ROUND_HALF_UP — estimated credit, weighed allocation (per-pickup round2, remainder to largest-est/earliest-created pickup, signed EARNED_FINAL_ADJUSTMENT deltas), contamination surcharge (BASE×TYPE_MULT×(1+0.5×min(strikes_before,3))), weekly invoice (per-line integer rounding then sum; residential WEEKLY_FLAT vs commercial METERED_BASE+OVERAGE_KG), credit application (min(balance, floor(0.5×subtotal)) — sole floor), account standing, lazy-quarter skip allowance, compost stock (0.3 yield), impact report (0.5 CO₂e/kg).
- **Validations**: every endpoint evaluates fixed PRD §2.10 order — auth(401) → role/ownership(403) → body shape(400) → path-then-body existence(404) → OCC(412) → state gates(409) → SoD(403) → fiscal(402/422) → structural(422/409) → temporal(422).

### PRD ambiguities resolved (choices made)
1. `ERR_INSUFFICIENT_STOCK` HTTP status — named in §3.8 but absent from §5 catalogue; mapped to 422 (matching other availability constraints).
2. Bin `version` on system-driven swaps — followed PRD §2.5: every mutation of a versioned resource bumps version (OCC only on plan-change, so safe).
3. Void after facility-tag forfeiture — voiding a COMPLETED pickup whose credit was already forfeited posts no second REVERSAL, preserving complete+void zero-drift invariant.
4. Strike threshold on later confirms — suspension triggers when strike_count >= 3 while ACTIVE (covers 4th-strike-after-resume), not only exactly reaching 3.
5. Ownership vs existence ordering — path resources resolved first (404) then ownership (403); pure string comparisons get 403 before 404 per priority table.
6. Entry `season` labels — EARNED_* entries use service_date's season; REVERSAL/MANUAL_ADJUSTMENT/REDEMPTION_DEBIT/INVOICE_APPLICATION_DEBIT use logical-now season.
7. Timestamps — created_at/updated_at from monotonic wall clock (never logical clock); resolved_at and all rule evaluations read the logical clock.
8. Multi-bin pickup completion — collected bin is earliest-created bin at customer; replacement is earliest-created clean depot bin of plan's type.
9. Pagination bounds — non-integer, limit<1 or >100, offset<0 → 400 ERR_INVALID_REQUEST.
10. Credit-adjustment `reason` — required; missing → 400.

## Step 5 (rerun notice): first Step 5 subagent exited before writing files — 2026-08-10T12:35:00.000Z

The first Step 5 subagent returned a filter-analysis report but wrote no files (`test_helpers/` and `test_suite/` absent on disk; verified). Re-running Step 5 with an explicit write-and-verify requirement. Step 6 output is intact and unaffected.

## Step 5 (rerun): Generate Unit Tests — 2026-08-10T12:46:23.676Z

All files written and verified. Complete summary:

### Test counts per queue
- **Queue A (Difficulty, §1.8): 18/18 instances covered, 36 tests** (exactly 2 per instance). All 18 passed the PRD-first two-condition filter — including the two `priority_pair_validation_conflict` instances, legitimately testable because PRD §2.10 explicitly pins the fixed evaluation order ("an earlier failure masks every later one") and names both competing error tiers verbatim.
- **Queue B (Corner, §1.9): 51/51 non-stub instances covered, 51 tests** (≥1 each). The 6 `excluded_because:` stubs in the `errors` section were NOT translated; cross-references verified — 5 resolve to queue-A instances, `err_stale_version_covered` resolves to corner `complexity_layers/plan_change_occ_stale_and_fresh`, which was translated.
- **Total: 87 tests, 87 Design tags** (36 `Design: Difficulty/...`, 51 `Design: Corner/...`). Zero instances skipped.

### test_helpers/ file list
`__init__.py` (barrel export), `types.py` (status/role enums + TypedDicts; ServicePlan and CompostCreditEntry carry only `id`+`created_at`), `api_client.py` (43 endpoint methods, one per PRD §4 row), `api_errors.py` (28 error ids; registered map excludes `ERR_INSUFFICIENT_STOCK` — see below), `assertions.py` (per-entity assertions + `assert_ledger_sum_matches_balance`), `factories.py`, `constants.py` (thresholds, season multipliers, surcharge tables, RES/COM plan defaults), `test_users.py` (`TEST_USERS` + `make_subscriber_headers` etc.), `fixtures.py` (5-tier composite helpers: `setup_active_subscription`, `setup_completed_pickup`, `setup_weighed_pickup`, `setup_issued_invoice`, `setup_delinquent_subscriber`, plus lifecycle shortcuts).

### On-disk verification output
- `ls test_helpers/` → 9 files; `ls test_suite/` → `conftest.py` + 9 test files.
- `grep -c 'def test_'`: 8, 15, 8, 14, 10, 12, 5, 10, 5 per file = **87 total**.
- `python3 -m py_compile` on all 19 files → OK; `pytest --collect-only` → **87 tests collected**, no import errors.
- Tag audit: queue A 18/18 with ≥2 tests, queue B 51/51 with ≥1, no unknown/dual/missing tags.
- Citation sweep: **133 quoted citations across 87 docstrings, all verbatim-match PRD.md** (22 initially failing quotes rewritten to full verbatim sentences, sweep re-run clean).

### Coverage-filter decisions of note
1. **`ERR_INSUFFICIENT_STOCK`** named in PRD §3.8 but has no HTTP status in §5 catalogue (none in scaffold error table either). Defined in `ApiErrorId` but deliberately omitted from the registered status map — `validate_error` checks only error_id for it; asserting an unregistered status would fail a PRD-faithful implementation.
2. **Initial `version` value** not pinned by PRD ("increments with every modification" only). Tests assert `isinstance(int)` / relative increments (`version + 1`) instead of hard-coding `version == 1`/`== 2`.
3. **Nullable pre-state fields** (`final_kg`, `collected_bin_id` on fresh pickups) asserted via `.get(...) is None` — satisfied by both `null` serialization and field omission, both PRD-consistent.
4. No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no freelance scaffold-walked tests.

(Orchestrator re-verified independently: 87 tests on disk across 9 test files.)

## Step 7: Run Tests and Iterate — 2026-08-10T12:50:15.962Z

**Exit condition met**: the very first 8-round parallel stability sweep came back clean — all 8 rounds report `passed == total` (87/87, 0 failed, 0 errors), verified both from the sweep's own summary and by re-reading each `results.{1..8}.json` directly. No diagnostic iterations were needed.

- **Iterations run**: 1 (single 8-round sweep, all rounds passed to completion; ~96s per round under full 8-way concurrency).
- **Tests deleted**: none. Union of failing tests across all 8 rounds was empty, so no PRD-coverage or unique-derivability audits were triggered.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.

The pre-existing artifacts are stable: 87 tests across 9 test files pass deterministically under `per-test-server` isolation with 8 concurrent rounds, including the timing-sensitive surfaces (weigh-ticket allocation tie-breaks, skip-cutoff boundary at exactly T−48h, OCC stale-version replay, suspension cascades, billing idempotency) that the parallel sweep is designed to stress.

(Orchestrator independently re-read all 8 `results.{1..8}.json`: each round passed=87 total=87 failed=0.)

## Step 8: Finalize PRD — SKIPPED — 2026-08-10T12:50:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. `PRD.md` already determined every behavior the implementation exhibits; `PRD_FINALIZED.md` is not produced. Step 9 will start from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-08-10T13:00:01.134Z

**File produced:** `workspace/PRD_COMPLETED.md` (Step 8 was skipped, so source was `workspace/PRD.md`).

**Size delta:** PRD.md = 276 lines / 49,424 chars → PRD_COMPLETED.md = 277 lines / 52,203 chars (**+1 line, +2,779 chars**; the one added line is the new §5 table row, everything else is inline).

**Counts:** 15 ambiguity-pins, 5 mismatch-revisions (20 changes total).

### Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)

1. §2.3 — insert — ambiguity — non-integer limit/offset, limit<1 or >100, offset<0 rejected with `ERR_INVALID_REQUEST` — `implementation/utils.py:152-172`
2. §2.3 — insert — ambiguity — `has_more` defined as true iff `offset` + returned-items < `total_count` — `implementation/response.py:27-32`
3. §2.5 — insert — ambiguity — `version` starts at 1 at creation; `updated_at` initially equals `created_at` — `implementation/db.py:72-77`
4. §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from monotonic wall clock, not the logical clock; logical clock governs rule evaluations and `resolved_at` — `implementation/db.py:48-63`
5. §2.6 — revise — mismatch — link-field rule: waiver credit-restore `MANUAL_ADJUSTMENT` carries `pickup_id`; operator-posted `MANUAL_ADJUSTMENT` carries no link field, only `reason` (PRD had said every entry has exactly one link field) — `implementation/services.py:227-241,383-385`
6. §2.6 — revise — ambiguity — per-type `season` rule: `EARNED_*` use the service date's season; `REVERSAL`/`MANUAL_ADJUSTMENT`/`REDEMPTION_DEBIT`/`INVOICE_APPLICATION_DEBIT` use the logical-now season at posting — `implementation/services.py:293,322,336,383,429`; `implementation/routes/billing.py:146,248,607`
7. §2.7 — insert — ambiguity — kilogram quantities serialized as JSON numbers — `implementation/utils.py:43-47`
8. §2.10 — revise — mismatch — ownership/existence interleave: bare subscriber references (path `/subscribers/{id}`, body `subscriber_id`) get 403-before-404 string comparison; path-addressed resources resolve first (404) then ownership (403) — `implementation/routes/subscriptions.py:47-51,100-106`; `implementation/routes/subscribers.py:39-43`; `implementation/routes/billing.py:71-75`
9. §2.10 tier 9 — insert — ambiguity — finished-compost stock availability added to structural constraints with `ERR_INSUFFICIENT_STOCK`, guarding redemption creation — `implementation/services.py:461-465`
10. §3.1 — revise — mismatch — dropped "unique" from plan `code` (impl enforces no code uniqueness) — `implementation/routes/plans.py:20-34`
11. §3.2 — insert — ambiguity — plan/subscriber `subscriber_type` equality evaluated only after all three ids resolve (dangling id → 404 first) — `implementation/routes/subscriptions.py:49-59`
12. §3.2 — insert — ambiguity — plan-change adds/removes no bins; assignment untouched — `implementation/routes/subscriptions.py:203-204`
13. §3.4 — insert — ambiguity — completion also fails `ERR_NO_BIN_AVAILABLE` when the subscription has no assigned bin; with multiple bins the collected one is the earliest-created assigned bin — `implementation/services.py:281-290`
14. §3.5 — insert — ambiguity — pause sets `service_status` to `PAUSED` immediately regardless of where the window lies vs the logical now — `implementation/routes/subscriptions.py:132-136`
15. §3.5 — insert — ambiguity — cancelling an already-`CANCELLED` subscription → `ERR_SUBSCRIPTION_STATE_CONFLICT` — `implementation/routes/subscriptions.py:163-165`
16. §3.6 — revise — mismatch — suspension triggers when strike count stands at **three or more** while `ACTIVE` (not only exactly reaching three) — `implementation/services.py:362-366`
17. §3.6 — insert — ambiguity — facility-tag forfeiture `REVERSAL` posted only when the earned amount is nonzero — `implementation/services.py:333-339`
18. §3.7 — revise — mismatch — void after facility-tag forfeiture posts no second `REVERSAL`; void `REVERSAL` only when earned amount nonzero — `implementation/services.py:316-324`
19. §3.8 — insert — ambiguity — missing credit-adjustment `reason` → `ERR_INVALID_REQUEST` — `implementation/routes/subscribers.py:68-70`
20. §5 — insert — ambiguity — added `ERR_INSUFFICIENT_STOCK | 422 Unprocessable Entity` catalogue row — `implementation/errors.py:39-41`

**Verified already-pinned (no change needed):** logical clock default `2026-05-01T00:00:00Z` (§2.4 vs `db.py:31`), bin `version` bumps on every mutation (§2.5 general rule vs `db.py:66-69`), replacement-bin selection (§3.4), skip-gate ordering allowance-before-cutoff (§2.10 tiers 8/10), weigh-ticket allocation/remainder/tie-break, credit-cap floor rounding, billing idempotency and response shape, segregation-of-duties after state gate (tiers 6/7). All confirmed against code.

## Pipeline complete — 2026-08-10T13:00:01.134Z

All done-when conditions satisfied: `workspace/PRD_COMPLETED.md` exists; worklog reaches `## Step 9`; final 8-round stability sweep all passing (87/87 × 8 rounds, `results.{1..8}.json` retained in `workspace/implementation/`). Step 8 skipped per zero-fix skip condition. One Step 5 rerun was required (first subagent exited without writing files); rerun produced 87 tests, all verified on disk.

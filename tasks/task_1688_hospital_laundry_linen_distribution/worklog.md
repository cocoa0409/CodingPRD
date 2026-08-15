# Worklog — task_1688_hospital_laundry_linen_distribution

## Step 1: Create Task Directory — 2026-08-14T08:05:00.000Z

Task directory `tasks/task_1688_hospital_laundry_linen_distribution/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. No index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T08:57:00.000Z

All artifacts generated and validated. Final report:

## Task complete — task_1688_hospital_laundry_linen_distribution

**Files written** (scenario embedded verbatim):
- `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Design summary**
- Complexity profile: `ledger_reconciliation` primary + `quota_allocation` secondary; layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency; **flat** topology (peer resources, FKs in bodies, `api_prefix: ""`), cyclic state-machine emphasis, **segregation_of_duties** role model (invoice creator ≠ finalizer; weight recording separated from billing), immediate consistency.
- 9 entities: Facility, Unit, LinenStock (catalog+inventory merged), ParLevel, CartExchangeRun, SoiledManifest, VendorInvoice, Complaint, SurgeEvent; 44 endpoints (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z); 24 error codes; 11 calculation rules; 2 OCC concurrency rules (par-level PUT, stock adjustments).
- Core couplings: weight-based provisional vs piece-count final vendor billing (890 vs 810 cents on identical data), posted vs accrual cost-per-adjusted-patient-day (11.20 vs 9.07), per-line-then-sum rounding pinned, credit evaluation order pinned, surge activation depth-3 cascade (posture → effective_par → reserve waterfall with CRITICAL-tier priority and `created_at` tie-breaks), complaint verify/rescind exact credit compensation, 5.00% loss-rate threshold (`>=`), closed-interval surge overlap vs 120-minute-buffer cart-run windows.

**§1.8**: 19 instances across all 9 rules (each ≥2, differentiation clauses honored). **§1.9**: 47 entries (45 active + 2 `excluded_because` stubs) spanning entities/state_machines/calculations/validations/endpoints/rbac/complexity_layers/consistency_model.

**Validation results**
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (625 calls scanned, 0 violations)
- Additional scripted audit: all `grounds:` refs resolve, all instance names unique across both files, every error code exercised by at least one recipe, no forbidden concurrency vocabulary.
- All formula-derived asserts were pre-computed with Python (e.g., provisional 890, final 810, credit 160 → billed 650, accrual 9.07, retirement crossing at exactly max_wash_cycles, 5.00% boundary via 1/20).
- One consistency fix during authoring: manifest-return now subtracts newly-retired pieces from circulation so the total-accounted-pieces invariant holds exactly (verified arithmetically per fixture).

## Step 3: Copy Shared Files — 2026-08-14T08:58:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1688_hospital_laundry_linen_distribution/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T09:10:00.000Z

PRD generated and verified. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/workspace/PRD.md` (approximately 230 lines, ending cleanly at the §5 error table). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Structure** (domain-derived, per the diversity rules):
- §1 Introduction — 2 paragraphs, business-context angle
- §2 Global Specifications — 10 subsections: RBAC (with per-role `identity:` translations, incl. `UnitClerk` entity-backed-to-`Unit`), verbatim §2.2 envelope, pagination, common resource properties, the logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), monetary precision, piece conservation/non-negativity, OCC, the 11-priority validation cascade in explicit prose order, and facility-scoped reference validation
- §3 Business Logic — 9 subsections organized by the linen loop: onboarding/catalog, pars & cart scheduling, cart completion & dispute–recount cycle, soiled manifests & isolation protocol, vendor return & shrinkage reconciliation, dual-basis invoicing, complaints & credits, surge reserve waterfall, cost-per-APD reporting
- §4 Endpoint table — 44 rows, 4 columns only; §5 Error catalogue — 24 errors, 2 columns only

**Key rules projected into prose**: dual invoice variants (weight-based provisional vs piece-count final) with pinned rounding/evaluation order, per-piece rate derivation, CRITICAL-stock/STANDARD-unit triage halving, wash-life FIFO retirement via `max_wash_cycles` crossings, 5.00% cumulative loss threshold → sticky `INVESTIGATION`, complaint credit routing (invoice `FINALIZED`/`DISPUTED` vs facility `credit_balance_cents` when `SETTLED`/uninvoiced) with exact rescind compensation, surge `effective_par` cascade and tier-ranked reserve waterfall with deficit-ratio tie-breaks, segregation of duties on finalize, and both OCC rules framed purely as stale-version rejections.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 65 required, 65 present, 0 missing
- endpoints[].request_body: 17 required, 17 present, 0 missing
- endpoints[].query_params: 11 required, 11 present, 0 missing
- path_params (via §4 backticked paths): 9 required, 9 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in ordered prose (§2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 18 checked (incl. system-driven Facility/LinenStock/Complaint transitions), 18 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose (no operators, no fuzzy wording), 0 missing
- validations[] conditions: 24 error ids all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed in the owning workflow subsections, 0 missing
- entities[].fields[] structured content: defaults/initials/enums all reconstructible (seeded counters, null-until-finalize totals, label-only severity, etc.), 0 missing
- sibling-branch symmetry: 6 groups checked (dispute/reconcile/finalize dual from-states, credit routing branches, posted vs accrual bases, verify vs reject role rule), all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 400
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-14T10:02:00.000Z

Generation complete. Summary of what was built and the key decisions:

## Deliverables

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/test_helpers/`
- `types.py` — 9 entity TypedDicts (all carry full common fields per PRD §2.4) + 14 status/category enums + `UserRole`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (38 methods incl. `/_clock/set_current_utc`).
- `api_errors.py` — all 24 error IDs with HTTP statuses, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `restock_totals()` (tolerant of zero-piece line omission), `assert_piece_conservation`.
- `factories.py`, `constants.py`, `test_users.py` — including `make_unit_clerk_headers(unit_id)` for the entity-backed UnitClerk role and two distinct LinenManager identities (`lm-1`/`lm-2`) for segregation-of-duties.
- `fixtures.py` — tiered composites: `base_scenario`, `fill_unit_to_par`, `collect_soiled`, `make_manifest`, `setup_returned/reconciled_manifest`, `setup_provisional/finalized_invoice`; all ownership-gated clerk calls thread the real `Unit.id`.

**`test_suite/` (13 files, 83 tests)** — `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/test_suite/`

## Audit results (all machine-checked)
- **Coverage**: all 19 difficulty instances have ≥2 tests; all 44 non-stub corner instances have ≥1; 3 `excluded_because:` stubs skipped with cross-references verified resolvable. 83 tests ↔ 83 `Design:` tags, each resolving verbatim to a real instance, each at docstring end, exactly one per test.
- **Citations**: every `PRD §x.y: "..."` quote verified verbatim against `workspace/PRD.md` (whitespace-normalized substring check — 0 failures).
- **Hygiene**: `py_compile`, full module import, and `pytest --collect-only` (83 collected) all pass; no skip/xfail markers; no scaffold references in comments/docstrings; pyflakes clean apart from the intentional barrel re-exports.

## Notable PRD-first adjudications
- **`provisional_total_rounds_per_line_then_sums`**: the design recipe invoices a DISPATCHED manifest, which PRD §3.6 rejects (`ERR_INVALID_STATE`). I repaired the setup minimally — a zero-piece return (allowed: `pieces >= 0`) puts the manifest in RETURNED without perturbing the weight-based provisional — keeping the pinned rounding claim (2 cents / 3 cents vs sum-then-round 1 / 2).
- **`expected_pieces_rounds_half_up`**: PRD never states `expected_pieces` appears on the manifest response, so the assertion observes it through the PRD-pinned dock-scale side effect (`in_wash` becomes 14) instead of response shape.
- **`restock_zero_when_on_hand_equals_par`**: zero-piece restock line representation is ambiguous to two PRD readers, so the test asserts total delivered pieces for the stock == 0 plus status/shortage/counter assertions rather than exact list equality.
- **`unit_quality_flag_watch_window_boundary`**: the +30-day window edge ("within the trailing 30 days") is not uniquely derivable (inclusive vs exclusive readings); kept the unambiguous count boundary (2→CLEAR, 3→WATCH), the +31-day falloff, and the 240-cent facility credit routing.
- **Version assertions**: PRD pins "increments by one on every mutation" but not the initial value, so creation-time version is asserted as int ≥ 1 and mutation tests assert relative increments (fresh+1) while absolute piece/cents values carry the conservation claims.

## Step 6: Generate Implementation — 2026-08-14T10:05:00.000Z

The implementation is complete and fully validated. 

## Summary

**Delivered** a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/workspace/implementation/`:

- `start.sh` — guarded install (`python3 -c "import flask"` check so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — blueprint registration, envelope-shaped 404/405/500 handlers
- `clock.py` — logical clock pinned at `2026-08-01T00:00:00Z`, never wall-clock
- `store.py` — empty in-memory tables (no seeding; verified)
- `errors.py` — all 24 catalog error IDs with exact HTTP statuses
- `util.py` — response envelope (`meta`/`response_type`/`data`, pagination fields inside `meta`), Decimal round-half-up helpers, field validators, OCC coercion (accepts int or numeric string)
- `auth.py` — `X-User-ID`/`X-User-Role` auth (unknown role → 401), per-endpoint role lists
- `services.py` — stock posture (strict `<` boundaries, `floor(1.5*rop)`), unit quality flag (trailing 30-day inclusive window on logical clock, computed on read), per-piece rate, cumulative loss rate over RECONCILED manifests
- `routes/` — 10 modules covering all 44 endpoints including `POST /_clock/set_current_utc`

**Validation**: 177 end-to-end checks passed against fresh boots, covering every pinned number from the difficulty/corner designs: provisional 890 vs final 810 (cpd 16.20), metrics posted 11.20 vs accrual 9.07, per-line-then-sum rounding (2 cents), CRITICAL-triage halving (15 pieces), dispute–recount cycle (on_hand 22 / in_wash 6), depth-3 surge cascade waterfall (CRITICAL-first, deficit-ratio, created_at tie-break), 5.00% loss-rate boundary (>=), wash-life crossing at exactly max_wash_cycles, OCC 412s, validation-priority pairs (MANIFEST_NOT_RECONCILED beats cap; ISOLATION_PROTOCOL_REQUIRED beats ALREADY_LINKED), window rules (120-min buffer, closed-interval surge adjacency), credit routing (FINALIZED/DISPUTED → invoice; PROVISIONAL/SETTLED/none → facility balance), verify/rescind exact compensation, auto-RESOLVED on reconcile, and late_delivery. Boot contract verified: `bash start.sh` from `./implementation/`, empty store at boot, 5 rapid kill/restart cycles all clean.

**Judgment calls worth noting**:
1. The `billed_total_credit_evaluation_order_pinned` design prose claims final 810/billed 650, but its own single-stock setup (7 returned × 80c) yields 560/400 — inconsistent with the pinned `cap_absent_allows_finalize` (560 for the identical manifest shape). I implemented the PRD formula faithfully; 810/650 corresponds to the two-stock manifest from the sibling instance.
2. Version bumps coalesce to one per resource per request — the corner instance pins a par level going v1→v2 across the whole activate cascade (effective_par recompute + waterfall on_hand).
3. Recount compensation applies against the currently-recorded (post-correction) soiled counts, as required by the cycle test's repeated recount of 6.
4. Invoice period `end <= start` → `ERR_INVALID_REQUEST` (PRD §3.6 explicitly overrides the generic `ERR_INVALID_WINDOW`).

## Step 7: Run Tests and Iterate — 2026-08-14T10:20:00.000Z

All 8 rounds of the stability sweep pass: 83/83 passed, 0 failed, 0 errors in every round.

## Summary

**Iterations run:** 2 (initial sweep → fixes → clean confirmation sweep; both sweeps were fully deterministic — identical failure sets across all 8 rounds in iteration 1, zero failures in iteration 2).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule; all failures were test-artifact bugs, not coverage gaps.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_unit_with_collection()` gained a `reconcile: bool = True` parameter forwarded to `collect_soiled()`. Three tests in `test_04_cart_run_dispute_recount.py` (`test_cycle_status_sequence`, `test_recount_compensation_and_overstock`, `test_dispute_reconciled_run_returns_already_terminal`) called the fixture with `reconcile=False`/`reconcile=True`, but the fixture silently funneled the kwarg into `base_scenario(**kwargs)`, raising `TypeError`. The PRD explicitly legitimizes a COMPLETED-but-unreconciled run ("reconciliation moves a run from `COMPLETED` to `RECONCILED`"), so the fixture now constructs exactly the precondition the tests express.

**Fixes applied to `test_suite/`:**
- `test_07_invoice_billing_calculations.py` — `TestCreditEvaluationOrder::test_verify_routes_credit_to_finalized_invoice` (billed 650→400), `test_refinalize_after_dispute_applies_credit_exactly_once` (final 810→560, billed 650→400), `TestFinalizeDisputeRefinalizeCycle::test_refinalize_recomputes_identical_totals` (810→560 ×3), plus the misleading `# final 810` setup comment.
- `test_09_complaints_and_credits.py` — `TestVerifyRescindRoundTrip::test_verify_prices_and_routes_credit` (billed 650→400) and `test_rescind_exactly_reverses_the_credit` (restored billed 810→560), plus the setup comment.

**Why (diagnosis):** The five credit/invoice tests asserted the pinned totals 810/650 against the shared single-stock fixture (`setup_finalized_invoice` / `setup_reconciled_manifest`: sheet stock 2.00 lbs at 40 c/lb → 80 c/piece, 7 pieces returned → final 560). The 810 figure belongs to the *two-stock* manifest (7 sheets + 10 isolation gowns) that `TestProvisionalVsFinal` correctly builds via its own `_setup_two_stock_reconciled_manifest()` — those tests passed all along. The PRD pins only the formula ("sum over every returned line of the line's returned `pieces` multiplied by its stock's per-piece rate"), never absolute totals, and two passing sibling tests (`test_cap_absent_allows_finalize`, `test_finalize_succeeds_after_manifest_reconcile`) independently assert 560 for the identical fixture shape. The scaffold difficulty-design recipes were internally inconsistent here (their `setup_api_calls` build the single-stock manifest while their prose claims 810/650) — a unit-test-generator miss where design-prose numbers were copied without re-deriving them from the recipe's own setup. Corrected assertions (560 final, 160 credit, 400 billed post-verify, 560 restored post-rescind) were verified arithmetically against the PRD formulas.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout; every failure was in the test layer.

## Step 8: Finalize PRD — 2026-08-14T10:30:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/workspace/PRD_FINALIZED.md` is produced.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 268 lines vs 268 lines — 0% delta. The file is a verbatim copy: **zero edits were justified by `<step_7_diff>`**.

**Changes:** None. Every step-7 fix was a pure test-layer bug against behavior the PRD already pins verbatim and the implementation already follows exactly. The step_7_diff itself confirms this: "The implementation was PRD-faithful throughout; every failure was in the test layer."

**Per-item search log (analysis mandatory per item; no edit committed for any):**

1. **`test_helpers/fixtures.py` — `reconcile` param on `setup_unit_with_collection()`**
   - (a) Subject: cart-run lifecycle precondition — a COMPLETED-but-unreconciled run that can be disputed, recounted, and reconciled.
   - (b) Impl paths enumerated: `implementation/routes/cart_runs.py` read in full — `dispute_cart_run` (accepts COMPLETED/RECOUNTED, RECONCILED→`ERR_ALREADY_TERMINAL`, lines 220-236), `recount_cart_run` (DISPUTED-only, lines 239-311), `reconcile_cart_run` (accepts COMPLETED/RECOUNTED, lines 314-330), `complete_cart_run` terminal guard (lines 150-154); cross-checked the three enabled tests in `test_suite/test_04_cart_run_dispute_recount.py` and the fixture chain in `test_helpers/fixtures.py:300-342`.
   - (c) No edit: PRD §3.3 pins this verbatim ("reconciliation moves a run from `COMPLETED` to `RECONCILED`, or from `RECOUNTED` to `RECONCILED`, and `RECONCILED` is terminal — … `ERR_ALREADY_TERMINAL` … `ERR_INVALID_STATE`"). The fixture bug was a `TypeError` from kwargs funneling — a harness bug, not PRD silence.

2. **`test_07_invoice_billing_calculations.py` — five corrected totals (final 810→560 ×3, billed 650→400 ×2)**
   - (a) Subject: invoice finalization math and credit evaluation order.
   - (b) Impl paths enumerated: `implementation/routes/invoices.py` — `create_invoice` provisional per-line rounding (lines 64-70), `finalize_invoice` per-piece rate cache → final total → billed = final − credit_total → cost_per_apd (lines 149-174); `implementation/routes/complaints.py` — `verify_complaint` credit pricing and FINALIZED/DISPUTED routing (lines 127-146); `implementation/services.py` — `per_piece_rate_cents` (line 44-46); verified fixture arithmetic (`2.00 lbs × 40 c/lb = 80 c/piece; 7 × 80 = 560; 2 × 80 = 160; 560 − 160 = 400`).
   - (c) No edit: PRD §2.6/§3.6/§3.7 pin the formulas and the evaluation order exactly as implemented; the PRD deliberately never pins absolute totals. The 810/650 figures were test-authoring arithmetic errors (copied from the two-stock recipe onto the single-stock fixture). Sibling tests (`test_provisional_total_is_weight_based`, `test_final_total_is_piece_count_reconciled`) confirm the two-stock 890/810 figures are consistent with the same PRD formulas.

3. **`test_09_complaints_and_credits.py` — corrected totals (billed 650→400, restored 810→560)**
   - (a) Subject: complaint verify/rescind credit round-trip.
   - (b) Impl paths enumerated: `implementation/routes/complaints.py` — `verify_complaint` (credit = `pieces_affected × per_piece_rate` at verify time; routes to invoice `credit_total_cents`/`billed_total_cents` when FINALIZED/DISPUTED, else facility `credit_balance_cents`; lines 112-151) and `rescind_complaint` (exact reversal via recorded `_credit_target`; lines 169-199); re-read `TestVerifyRescindRoundTrip` in `test_suite/test_09_complaints_and_credits.py:191-250`.
   - (c) No edit: PRD §3.7 pins the credit formula, routing rule, and "exact compensation of verification" verbatim; impl matches. Corrected assertions are pure arithmetic fixes.

**Neighboring ambiguities noted but deliberately left untouched (out of HARD SCOPE — no listed step-7 fix traces to them, no failing test depended on them):** recount guard/compensation phrasing "original soiled pieces recorded" vs the impl's currently-recorded (post-merge) counts in repeated dispute–recount cycles (`cart_runs.py:257-279`), and credit routing when the referenced invoice is PROVISIONAL (`complaints.py:131-141`). Per the NO-NEW-MISMATCH rule's "prefer under-determined wording" guidance, both were left as-is rather than risk introducing a false universal claim.

## Step 9: Complete PRD — 2026-08-14T10:50:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1688_hospital_laundry_linen_distribution/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` 268 lines / 41,582 chars → `PRD_COMPLETED.md` 268 lines / 44,866 chars (char-delta +3,284; all changes in-paragraph, no new sections, no added lines).

**Counts:** 23 ambiguity-pins (inserts), 3 mismatch-revisions.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — blank/whitespace-only `X-User-ID`/`X-User-Role` headers also reject as `ERR_UNAUTHENTICATED` — implementation/auth.py:21-26
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to ≥0), non-integer values reject `ERR_INVALID_REQUEST`; `created_at` ties broken by creation order; `has_more` = `offset` + returned count < `total_count` — implementation/util.py:121-147
- §2.4 — insert — ambiguity — `version` starts at 1 at creation; at most one version bump per resource per request; untouched resources not bumped — implementation/util.py:293-306, routes/cart_runs.py:189-200, routes/surges.py:103-146
- §2.5 — insert — ambiguity — all server-generated timestamps (`created_at`, `updated_at`, `api_request_timestamp`, `completed_at`) read the logical clock; clock accepts any valid instant (no monotonicity constraint) — implementation/util.py:24-25, clock.py:15-19, routes/clock_routes.py:12-23
- §3.1 — insert — ambiguity — facility field validation: `rate_per_lb_cents` int ≥ 0, `isolation_surcharge_pct` number ≥ 0, `monthly_cap_cents` int ≥ 0 when present — implementation/routes/facilities.py:23-31
- §3.1 — insert — ambiguity — duplicate `sku` within a facility rejects `ERR_INVALID_REQUEST` — implementation/routes/stocks.py:48-51
- §3.1 — insert — ambiguity — stock field validation: `piece_weight_lbs` number > 0; `unit_cost_cents`/`reorder_point_pieces`/`opening_pieces`/`opening_reserve_pieces` ints ≥ 0; `max_wash_cycles` int ≥ 1 — implementation/routes/stocks.py:28-45
- §3.2 — insert — ambiguity — `base_par_quantity` must be an integer ≥ 0 — implementation/routes/par_levels.py:25-27
- §3.2 — insert — ambiguity — new run also starts with `soiled_lines`/`restock_lines` empty and `storage_attested` null (set true at completion, carried thereafter) — implementation/routes/cart_runs.py:91-104, serializers.py:81-96
- §3.3 — insert — ambiguity — duplicate `stock_id` entries in `soiled_lines` are summed into one per-stock count — implementation/routes/cart_runs.py:53-64
- §3.3 — insert — ambiguity — a stock with no par level on the unit counts as `on_hand` zero for `ERR_COUNT_EXCEEDS_ON_HAND` — implementation/routes/cart_runs.py:164-171
- §3.3 — insert — ambiguity — restock deficit is computed for every par level configured on the unit (not only collected stocks), in par-level creation order — implementation/routes/cart_runs.py:173-185
- §3.3 — insert — ambiguity — `restock_lines` carries one entry per par level of the unit, in par-level creation order, including zero-piece entries — implementation/routes/cart_runs.py:201
- §3.3 — insert — ambiguity — dispute `reason` accepted but not persisted or returned — implementation/routes/cart_runs.py:225
- §3.3 — revise — mismatch — recount caps and compensation are computed against the **currently recorded** soiled counts (a recount rewrites the run's `soiled_lines`; "original" → "currently recorded"); count check runs after state and ownership guards; aggregation per `stock_id` as in completion; top-up is per corrected line's stock with no triage halving — implementation/routes/cart_runs.py:248-302
- §3.4 — insert — ambiguity — manifest line `stock_id`s must resolve to stocks of the given facility, else `ERR_NOT_FOUND` — implementation/routes/manifests.py:46-55
- §3.4 — insert — ambiguity — derived `expected_pieces` is carried on each manifest line in responses — implementation/routes/manifests.py:83-85, serializers.py:99-108
- §3.5 — insert — ambiguity — `returned_lines` require both `pieces` and `condemned_pieces` as integers ≥ 0 (condemned is not optional) — implementation/routes/manifests.py:157-169
- §3.6 — insert — ambiguity — invoice dispute `reason` accepted but not persisted or returned — implementation/routes/invoices.py:183
- §3.7 — insert — ambiguity — conditional complaint-role check runs after the complaint is loaded, so an unknown complaint id surfaces `ERR_NOT_FOUND` first — implementation/routes/complaints.py:119-122
- §3.7 — revise — mismatch — credit routing: a manifest on a `PROVISIONAL` (not yet finalized) invoice routes to the facility `credit_balance_cents`, same as `SETTLED`/uninvoiced (PRD's dichotomy omitted PROVISIONAL) — implementation/routes/complaints.py:131-146
- §3.7 — insert — ambiguity — complaint reject `reason` accepted but not persisted or returned — implementation/routes/complaints.py:159
- §3.7 — insert — ambiguity — `RESCINDED` is a terminal state — implementation/routes/complaints.py:16,177-179
- §3.7 — insert — ambiguity — quality-flag trailing-30-day window boundary is inclusive (complaint created exactly 30 days ago still counts) — implementation/services.py:24-34
- §3.8 — insert — ambiguity — `par_multiplier` must be a number > 0, else `ERR_INVALID_REQUEST` — implementation/routes/surges.py:29-31
- §4 — revise — mismatch — stock-adjustment recording returns `201 Created` with the updated stock, carved out of the blanket "modifications return 200" rule — implementation/routes/stocks.py:126

**Notable areas verified already-aligned (no change):** validation-order pipeline per §2.9 (checked endpoint-by-endpoint), all state machines and terminal guards, all calc formulas (posture thresholds, expected pieces RHU, per-piece rate, wash-life FIFO crossings, loss-rate 5.00% sticky flip, provisional/final invoice math with per-line rounding, metrics posted/accrual bases), OCC guards, surge waterfall ranking, full error catalogue (IDs + HTTP statuses), endpoint table and RBAC.

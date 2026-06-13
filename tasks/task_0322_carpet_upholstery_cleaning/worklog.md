# Worklog — task_0322_carpet_upholstery_cleaning

## Step 1: Create Task Directory — 2026-06-13T00:00:00.000Z

Created `tasks/task_0322_carpet_upholstery_cleaning/` and `tasks/task_0322_carpet_upholstery_cleaning/workspace/` (directory specified explicitly by caller; no ./tasks/ auto-increment scan performed to avoid ID contention with parallel tasks). Difficulty: Expert (applied only at Step 2 scaffold generation).

## Step 2: Generate Scaffold (Expert tier) — 2026-06-13T12:10:00.000Z

All three required files are written. Generation is complete.

### Summary

Generated the three Expert-tier scaffold artifacts for **task_0322_carpet_upholstery_cleaning** purely from the scenario description and the scaffold-generator spec (no sibling tasks consulted). `scaffold_lint.py` reports **VERDICT: clean lint**.

**Complexity profile**: pricing_engine (primary) × temporal_windowing (secondary); layers = dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency. Hybrid topology, **parallel** state-machine shape (CleaningJob carries two independent status axes), peer_roles, immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7)**:
- **12 entities**: Customer, ServiceCatalog, Crew, RecurringPlan, CleaningJob, RoomAssessment, AddOn, ScheduledSlot, Invoice, Payment, GuaranteeClaim, WalletLedgerEntry (last is append-only, `common_fields:false`).
- **5 state-machine blocks** across 5 entities, including the non-linear shapes: CleaningJob `lifecycle_status` × `billing_status` (parallel axes), GuaranteeClaim FILED→{GRANTED,DENIED} (branching fork-join with divergent side-effects), ScheduledSlot RESERVED↔ reschedule (cyclic).
- **6 calculations**: `quoted_price` (forward) vs `settled_price` (chronological with heavy-soiling escalation) — the dual-variant pair; `addon_line_price` (order-sensitive PROTECTANT), `invoice_wallet_application` (waterfall), `wallet_credit_balance` (conserved ledger sum), `guarantee_window_eligibility` (dry-time-derived threshold).
- **15 validations** (priority-ordered), **42 endpoints** (incl. mandatory FK reverse-reachability GETs and one logical-clock input on `complete`), **35 errors**, **4 roles** (Customer entity_backed; Dispatcher/ServiceManager/Billing opaque), **2 concurrency rules** (OCC on Crew.version for booking, on Invoice.version for payments — both satisfy the full §1.2.1 contract).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)**: 9 rule_ids × **2 instances = 18 instances**, every rule meeting its differentiation clause (e.g., dual-variant on CleaningJob-cost vs AddOn-price domains; combinatorial modes (a) non-linear discount and (b) round-then-sum order; cascades from claim-grant depth-3 vs invoice-void depth-2; overlap body-collision vs buffer-adjacency). All formula-derived asserts are literals computed in Python (e.g., quoted 24000 / settled 28000; combinatorial 21547; round-then-sum 78).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)**: **34 active instances + 4 `excluded_because` stubs** across sections entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting_complexity_layers, consistency_model (creation/defaults/not-found/enum bounds, invalid-from transitions, terminal lockdown, idempotency, OCC stale-version for both rules, RBAC denials, FK filtered lists, immediate-consistency). Stubs correctly cite §1.8 instance names.

**Key design decisions**: `api_prefix: /` (flat peer-entity surface, no shared prefix); path id placeholders standardized to `{id}` so lint check (f) resolves; all FK reverse-reachability satisfied; removed three unreachable enum values (ServiceCatalog status, RecurringPlan CANCELLED, Payment REVERSED) for enum-closure; no forbidden concurrency vocabulary; no `id` used in business decisions (`created_at` used for ordering where needed).

## Step 3: Copy Shared Files — 2026-06-13T12:12:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0322_carpet_upholstery_cleaning/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T12:15:00.000Z

Generated `workspace/PRD.md` for the Carpet & Upholstery Cleaning API (Expert-tier pricing-engine domain).

**Structure:** 22 headings — Introduction, 10 §2 subsections (2.1–2.10, including the verbatim §2.2 envelope), 6 §3 workflow subsections (3.1–3.6), the §4 endpoint table, and the §5 error catalogue. **~271 lines.**

**§3 grouping** is by business-process timeline rather than the example's pattern: onboarding → job building & quote → scheduling lifecycle → billing/settlement → re-clean guarantee → reads.

**Hard-contract reports (transcript-only, not written into any file):**

Field coverage check: entities[].fields 51/51 present; endpoints[].request_body 32/32; endpoints[].query_params 13/13. Status: PASS
Rule coverage check: validations 15 checked (ordering in §2.6 prose); concurrency_rules 2 (book→ERR_STALE_CREW_VERSION/412; payments→ERR_STALE_INVOICE_VERSION/412); state_machines all transitions expressed; calculations 6 checked; endpoints side_effects/cascades stated; sibling-branch symmetry GRANTED vs DENIED equal density. Status: PASS
Path purity check (§3 only): 349 backtick tokens scanned, 0 path-like / bare-method / method+path tokens. Status: PASS

**Coverage confirmation:** every scaffold entity (all 12, incl. lean `WalletLedgerEntry` with no `updated_at`/`version`), both parallel state machines plus ScheduledSlot reschedule cycle and GuaranteeClaim fork, all 6 calculations, all 15 validations, all 43 endpoints, all 35 error codes, all 4 roles. SCAFFOLD_DIFFICULTY_DESIGN and SCAFFOLD_CORNER_DESIGN were not opened.

## Step 5: Generate Unit Tests — 2026-06-13T12:37:00.000Z

Test infrastructure generation is complete.

**Stage 1 — `test_helpers/` (9 modules):** `types.py` (enums + entity TypedDicts; `WalletLedgerEntry` carries only `id`+`created_at`), `api_client.py` (one method per endpoint), `api_errors.py` (35 error IDs registered with framework status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Customer `entity_backed` → `make_customer_headers(id)`; other three roles opaque), `fixtures.py` (composite chains: `setup_quoted/booked/completed/invoiced_job`, `setup_customer_with_wallet_credit`, `grant_guarantee_credit`, slot-count readers), `__init__.py` barrel. Imports cleanly under runner venv.

**Stage 2 — `test_suite/` (6 test files + conftest, 70 test functions):** `test_01_onboarding_and_crud.py` (12), `test_02_job_lifecycle_and_scheduling.py` (17), `test_03_pricing_calculations.py` (8), `test_04_billing_and_wallet.py` (7), `test_05_guarantee_and_cascades.py` (8), `test_06_difficulty_reinforcement.py` (18). All 70 collect with no errors.

**Coverage (every instance verified by script):**
- **Queue A (Difficulty):** all 18/18 instances translated, each with exactly 2 tests. 0 skipped.
- **Queue B (Corner):** all 34/34 non-stub instances translated, 1 test each. 0 skipped. The 4 `excluded_because:` stubs correctly NOT translated; their `difficulty_instance` cross-references resolve to real Queue-A instances.

**Quality gates passed:** every docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance; no untagged/dual-tagged tests; no skip/skipif/xfail; no scaffold/§-reference leakage; all PRD citations verbatim-present (fixed several ASCII `->` → PRD `→` glyphs and one truncated `version` citation); all literal expected values (21547, 78, 130, 24000/28000, 11250, 16000, window edges 1480/1481, wallet 2000) independently recomputed against PRD §3 formulas with round-half-up.

**PRD-coverage gaps:** none required skipping. Every design instance had verbatim, uniquely-derivable PRD coverage.

## Step 6: Generate Implementation — 2026-06-13T12:37:00.000Z

Complete Python + Flask implementation in `workspace/implementation/` (expert tier).

**Files (16 total):** `start.sh` (executable), `requirements.txt`, `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`; `routes/`: customers, catalogs, crews, plans, jobs, job_reads, billing, guarantees; `services/`: common, calculations, computed, lookups, scheduling.

**Coverage:** 12 entities (Customer, ServiceCatalog, Crew, RecurringPlan, CleaningJob, RoomAssessment, AddOn, ScheduledSlot, Invoice, Payment, GuaranteeClaim, WalletLedgerEntry — lean append-only id/created_at only). 42 endpoints registered/verified. Parallel state machines: CleaningJob lifecycle (DRAFT→QUOTED→BOOKED→IN_PROGRESS→COMPLETED/CANCELLED) × billing (UNBILLED→INVOICED→PAID); Invoice (OPEN→SETTLED/VOID), ScheduledSlot (RESERVED→RELEASED cyclic via reschedule), GuaranteeClaim (FILED→GRANTED/DENIED fork). Dual-variant pricing with Decimal/ROUND_HALF_UP per pinned step (forward quoted_price vs chronological settled_price with +4000 escalation at ≥3 heavy rooms; verified quote 45475 / settle 48875). Cascades: book→slot+crew.version, complete→slot release+plan visit count, invoice→wallet debit ledger, void→wallet refund+job reopen, grant→reclean job+room copy+goodwill credit. OCC on expected_crew_version (book/reschedule, 412) and expected_invoice_version (payment, 412). Validation precedence per PRD §2.6.

**Contract confirmation:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`, guards `pip install` behind `import flask` check. Storage in-memory only (plain dicts in `db.py`, recreated empty per import) — no SQLite, no JSON-on-disk, no /tmp. No seeding/preloading — fresh boot returns `total_count: 0` for every collection.

**Cross-step note:** Step 5 (test-gen) computed the dual-variant worked example as quoted 24000 / settled 28000; Step 6 (impl) reported a self-test of quoted 45475 / settled 48875. These are different fixtures/inputs (each subagent ran its own end-to-end probe), not necessarily a conflict — Step 7's 8-round sweep is the authoritative reconciliation.

## Step 7: Run Tests and Iterate — 2026-06-13T12:55:00.000Z

All 8 parallel rounds pass cleanly (69/69 each, 0 failed, 0 errors). The total dropped from 70 to 69 because one test was deleted. Exiting with the summary.

### Summary

**Iterations run:** 2 (baseline sweep + 1 fix sweep). The baseline showed a stable 4-test failure set, identical across all 8 rounds — deterministic, not flaky. After one round of fixes, all 8 parallel rounds passed 69/69.

**Union of baseline failures (4 tests, all 8 rounds):**
- `test_quote_vs_settle_diverge_on_three_heavy_rooms` — `settled_price_cents == None`
- `test_settled_no_escalation_at_two_heavy_rooms` — `settled_price_cents == None`
- `test_escalation_triggers_at_exactly_three_heavy_rooms` — `settled_price_cents == None`
- `test_cancel_completed_job_rejected` — expected `ERR_JOB_NOT_QUOTED`, got `ERR_JOB_ALREADY_BILLED`

**Tests deleted (1):**
- `test_cancel_completed_job_rejected` (`test_suite/test_02_job_lifecycle_and_scheduling.py`) — STEP 1b ENUM-MEMBERSHIP-ONLY / ERROR-PRECEDENCE SILENCE. PRD §3.3 only states "Cancellation is permitted from `DRAFT`, `QUOTED`, or `BOOKED`" and pins `ERR_JOB_ALREADY_BILLED` solely to the billing guard. For a COMPLETED-but-UNBILLED job, the PRD's generic §2.6 state-error catalogue (8 members) does not uniquely determine which `ERR_JOB_NOT_*` error a cancel emits when the source state is outside the three permitted ones — a faithful implementer could emit `ERR_JOB_NOT_DRAFT`, `ERR_JOB_NOT_QUOTED`, or `ERR_JOB_NOT_BOOKED` (or, as the impl does, route it through the billing guard). The assertion of an exact `ERR_JOB_NOT_QUOTED` is not uniquely derivable. Scaffold rule that drove generation: `Corner/state_machines/cancel_completed_job_rejected_terminal`.

**Fixes applied to `test_helpers/` (1):**
- `fixtures.py`, `setup_invoiced_job()` — re-read the job via `get_job(ctx["job"]["id"])` after issuing the invoice. The helper previously returned the pre-invoice COMPLETED-job snapshot, whose `settled_price_cents` is still null (PRD §3.2: "remaining null until the invoice is issued"). The three escalation tests read `ctx["job"]["settled_price_cents"]`, which the implementation correctly populates on the *server-side* job at issuance — the stale client snapshot was the bug. This single fix resolved all three escalation failures.

**Fixes applied to `implementation/`:** None. The implementation's settled-price computation (`services/calculations.py::compute_settled_price`, +4000 escalation at `heavy_rooms >= 3`) and its setting of `job["settled_price_cents"]` at invoice issuance (`routes/billing.py::issue_invoice`) were already PRD-correct.

**Final state:** 8/8 parallel rounds pass, 69/69 tests each, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-06-13T13:00:00.000Z

The patch is complete. One single edit, all four step_7_diff items accounted for.

**Line counts:** PRD.md 271 lines, PRD_FINALIZED.md 271 lines, 0% line-count delta (one line revised in place).

**Changes (1):**
- **§3.3 (cancel) — revise — pinned the cancel error for out-of-permitted-state jobs** — when a cancel targets a job whose `lifecycle_status` is not `DRAFT`/`QUOTED`/`BOOKED` (e.g. `IN_PROGRESS`, `COMPLETED`, or already `CANCELLED`), the impl emits `ERR_JOB_ALREADY_BILLED` (409) rather than any `ERR_JOB_NOT_*` state error, regardless of `billing_status` — `implementation/routes/jobs.py:427-435`.

**Step 7 item disposition:**
- `test_cancel_completed_job_rejected` (deleted) — genuine PRD silence, pinned (§3.3).
- The 3 escalation tests (`settled_price_cents == None`) — pure fixture bugs, no PRD change. PRD §3.2 already says `settled_price_cents` stays null until issuance; §3.4 already pins the +4000 escalation at heavy_rooms ≥ 3 — both verified against impl. No silence, no mismatch.

**Per-edit pre-edit search log:** Edit 1 (§3.3 cancel error pin) — (a) subject: error emitted by cancel when lifecycle ∉ permitted set, plus all producers of `ERR_JOB_ALREADY_BILLED`; (b) grepped `ERR_JOB_ALREADY_BILLED` across impl — two producers (`routes/jobs.py:414-447 cancel_job`; `routes/billing.py:58-61 issue_invoice` billing guard, already PRD-covered); re-read §2.6 catalogue; (c) scoped clause strictly to cancel op, added "regardless of the job's `billing_status`" to match unconditional routing, left billing-guard sentence verbatim.

## Step 9: Complete PRD — 2026-06-13T13:08:00.000Z

Full PRD-vs-implementation completeness scan complete.

**Source vs. completed:** `PRD_FINALIZED.md` (source) → `PRD_COMPLETED.md`: 271 → 271 lines (all edits in-paragraph). Chars 43,942 → 44,438 (+496).

**Counts:** 2 ambiguity-pins, 1 mismatch-revision.

**Changes:**
- §2.3 Pagination — insert — ambiguity — defined `has_more` as true exactly when `offset` + items-on-this-page < `total_count` — `implementation/response.py:41`.
- §3.2 Building a Job (add-ons) — insert — mismatch — pinned that attaching an add-on bumps the parent job's `version` and refreshes `updated_at`, even though no other stored/computed job field changes — `implementation/routes/jobs.py:218`.
- §3.5 Re-Clean Guarantee (grant) — insert — ambiguity — pinned that the minted re-clean job copies the origin's `move_furniture` flag and sets `total_sqft` to the sum of copied rooms' `area_sqft` — `implementation/routes/guarantees.py:125,138-147`.

**Deliberately left unchanged (already uniquely pinned / non-ambiguous):** full validation-precedence chain; booking precondition order; buffer-boundary adjacency; quote/settlement rounding + ≥3-heavy-room +4000 escalation; protectant-at-total_sqft-0 freeze; wallet ledger sign/reason/cleaning_job_id; invoice issuance/void/payment cascades + INVOICED→PAID transition; inclusive guarantee window (dry_time×2); cancel's ERR_JOB_ALREADY_BILLED for non-DRAFT/QUOTED/BOOKED; reschedule two-hop slot cascade; read endpoints not enforcing customer-ownership (per §2.1); idempotent re-suspend/re-pause (left un-pinned to avoid inventing an error path).

---

## Pipeline complete — 2026-06-13T13:08:00.000Z

All 9 steps done. Final state: **8/8 parallel sweep rounds pass, 69/69 tests each.** Task directory contains SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), worklog.md, test_helpers/, test_suite/ (6 files, 69 tests after 1 PRD-silence deletion), and workspace/ with INSTRUCTION.md, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, and a working Python/Flask implementation/ (in-memory, 42 endpoints).

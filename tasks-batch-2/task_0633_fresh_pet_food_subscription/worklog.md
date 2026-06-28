# Worklog — task_0633_fresh_pet_food_subscription

Scenario: 633. Fresh Pet-Food Subscription (The Farmer's Dog/Ollie style): pet profile & portion/calorie calculation, vet-formulated recipe & allergen, recurring delivery cadence & cold-pack shipping, plan resize on weight change, skip/pause/swap, billing & renewal, transition schedule, referral credit

Difficulty band: Expert (Step 2 only)

## Step 1: Create task directory — 2026-06-23T02:42:43.000Z

Task directory `tasks/task_0633_fresh_pet_food_subscription/` was pre-assigned and pre-created (with `workspace/`). Skipped the max-index scan per orchestration directive. Verified directory + empty workspace exist; INSTRUCTION.md and all prd-bench skills present at project root.

## Step 2: Generate scaffold (Expert band) — 2026-06-23T03:15:52.000Z

All three scaffold artifacts are written and pass the lint cleanly. The hard constraint was honored — built the scaffold purely from the scenario description and the scaffold-generator skill spec, without reading any sibling `task_*/` directory.

Generated the Expert-band scaffold. All three files written and lint-clean:
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1179 lines, no scaffold_difficulty_design/scaffold_corner_design key
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) — 1234 lines, top key scaffold_difficulty_design
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) — 1630 lines, top key scaffold_corner_design

**Structural profile (Expert band):**
- **Entities: 8** — Account, Pet, Recipe, Subscription, WeightLog, Order, Shipment, ReferralCredit
- **State machines: 4** — Subscription (cyclic: ACTIVE↔PAUSED, PAST_DUE→ACTIVE recovery, PAST_DUE→CANCELLED), Order (branching: SCHEDULED→{SKIPPED,CHARGING}, CHARGING→{PAID,FAILED}, FAILED→CHARGING retry), Shipment (linear + spoilage fork), Recipe (DRAFT→PUBLISHED→RETIRED)
- **Calculations: 6** — daily_calorie_target (RER × 4 nested multipliers), cycle_price (grams-first rounding, volume tiers, estimate/actual dual-variant), shipping_fee (free-ship threshold), order_charge_settlement (pinned shipping-before-credit waterfall), coolant_packs (mass+transit tiers), referral_credit (capped flat grants)
- **Endpoints: 42** (flat topology under `/api`, plus `/_clock` test-driving endpoints with default clock 2026-01-01T00:00:00Z)
- **Error catalog: 42**
- **RBAC roles: 5** — PetParent (entity_backed:Account), NutritionVet, BillingAdmin, FulfillmentOps, Anonymous (peer_roles model)
- **Concurrency rules: 2** — OCC stale-version on order-generate and resize (both on Subscription.version, 412)

**§1.8 instance counts:** 19 total — all 9 §0.5 rule_ids covered, each ≥2 (combinatorial_formula has 3 covering modes a/b/c).
**§1.9 instance counts:** 43 total (38 active + 5 `excluded_because` stubs) across 9 taxonomy sections; all stub refs resolve to named §1.8 instances.

**Key engineering notes:** flat topology for FK reverse-reachability; all formula-derived assertions pre-computed literals (dct 794/911/662, cycle_price 8004/7003/5107/3965, settlement total 5223/3223, coolant 5/6, referral grants 1500/2000; conservation invariants gross 5223, total granted 3500); life_stage age boundaries pinned as calc constant; restructured two cascade chains to generate sibling orders while ACTIVE; added producing path for REVOKED referral-credit enum. 463 setup/trigger calls scanned, zero lint violations.

## Step 3: Copy INSTRUCTION.md — 2026-06-23T03:15:52.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0633_fresh_pet_food_subscription/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-23T03:20:57.000Z

Generated `workspace/PRD.md` (306 lines) for the Fresh Pet-Food Subscription domain (pricing-engine + workflow-orchestration, Expert band). Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

### Section structure
- **§1 Introduction** — 3 paragraphs
- **§2 Global Specifications** — 10 subsections: Access Control, Response Structure (verbatim), Pagination, The Logical Clock, Common Resource Properties & Versioning, Precision/Rounding/Monetary, Hierarchical Consistency & Cascades, OCC on Subscriptions, Validation Ordering, Left-to-Right Existence Resolution
- **§3 Business Logic & Workflows** — 9 subsections: Accounts/Referral/Wallet, Recipes, Pets & Caloric Target, Weight Logging & Resize Cascade, Subscription Creation/Activation/Estimate, Skip/Pause/Resume/Cancel/Generation, Billing Waterfall, Referral Credit Grant/Revoke, Cold-Pack Shipping
- **§4 Endpoint Definitions** — 4-column table (43 endpoints)
- **§5 Error Code Catalogue** — 2-column table (43 error IDs)

### Hard Contracts (all PASS)
- Contract 1 (Field-Name Coverage): all 67 scaffold field names + endpoint params present in backticks — 0 missing.
- Contract 2 (Rule Coverage): all 5 calculations rendered as precise prose; both OCC entries express write_endpoint + expected_subscription_version + ERR_STALE_SUBSCRIPTION_VERSION (412); all state transitions, cascades, validation priority ordering expressed; all 42 enum/state values present.
- Contract 3 (§3 Path Purity): 468 §3 backtick tokens scanned — 0 paths/methods/method+path combos.
- §2.2 emitted byte-for-byte verbatim.

## Step 5: Generate unit tests — 2026-06-23T03:33:17.000Z

Generated complete test infrastructure strictly from the two design indices (no freelance discovery).

**Test files: 9** (`test_suite/test_01..test_09`), **77 tests total**, all collect and byte-compile cleanly.

**Coverage by queue:**
- **Queue A (Difficulty, §1.8):** all 18 non-stub instances across 9 rules, each covered by ≥2 tests (39 difficulty-tagged tests; `free_ship_threshold` has 4). Primary tests in test_01–test_07; second angle for every difficulty instance in test_09.
- **Queue B (Corner, §1.9):** all 37 non-stub instances covered by ≥1 test (38 corner-tagged tests). The 5 `excluded_because:` stubs correctly NOT translated.

**Instances skipped:** none (every non-stub instance passed the PRD-first two-condition filter).

**Audits passed:** every docstring ends with one `Design: Difficulty/...` or `Design: Corner/...` line verbatim from YAML `name:`; all sampled PRD citations survive literal grep; all computed literal assertions independently re-derived; no skip/skipif/xfail; no scaffold leakage. WeightLog modeled append-only; PetParent identity via `make_pet_parent_headers(account_id)`.

**test_helpers/ files (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` + `test_suite/conftest.py`.

Downstream note: tests assume spoilage/referral-credit list endpoints return MAKE_GOOD/SIGNUP rows filterable by `referred_account_id` (PRD-grounded; make-good row sets `referred_account_id` to beneficiary account).

## Step 6: Generate implementation — 2026-06-23T03:33:17.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

**Files (11):** `start.sh` (executable foreground launcher), `requirements.txt` (`flask==3.0.3`), `app.py` (entry + error handlers + all route handlers), `auth.py`, `errors.py`, `response.py`, `requtil.py`, `store.py` (in-memory dicts + logical clock default `2026-01-01T00:00:00Z`), `calc.py` (six calculation rules, `Decimal` round-half-up), `domain.py`, `serialize.py`.

**Deps:** Flask 3.0.3 only; stdlib otherwise (`decimal`, `datetime`, `uuid`).

**Endpoints: 45** — 2 clock, 6 accounts/referral, 5 recipes, 5 pets, 3 weight-logs, 11 subscriptions, 6 orders, 5 shipments, 2 referral-credit reads.

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground, guards pip install behind import check.

**Storage:** purely in-memory module-level dicts, constructed empty at import. No SQLite/JSON/tmp. No `seed_*`; tests build all state via API.

Self-verification smoke passes covered auth, register/referral, calorie target (472 kcal/10kg adult dog), cycle-price estimate (15876c w/ 10% tier), OCC stale, order generate/charge/settle + first-paid referral grant, shipping boundary, coolant, dispatch/deliver, spoilage make-good, 3-decline PAST_DUE→CANCELLED, skip/pause/resume, resize, weight-log cascade, allergen/species/region gates, ownership + left-to-right existence ordering, cancel-revokes-pending-signup.

Interpretation flagged: `actual` cycle-price variant on order (`food_subtotal_cents`) computed from subscription's current `pack_total_grams` snapshot (§3.5 "frozen onto the Order at generation"), reusing round-grams-first-then-scale.

## Step 7: Run tests + iterate to green — 2026-06-23T04:16:49.000Z

### Subagent summary (verbatim)

All 8 parallel rounds pass cleanly (77/77 each). Exiting with the summary.

**Iterations run:** 2 (baseline sweep at 43/77, then one fix batch → 77/77 across all 8 rounds).

**Tests deleted:** None. Every failing test traced to a PRD-covered, uniquely-derivable rule; all failures were a fixture bug or an implementation bug, not test unfairness.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `create_published_recipe` and `create_draft_recipe`: now default `availability_regions` to `["US", "CA"]` when not overridden. This was the root cause of 32 of 34 failures: the shared fixtures built recipes with an empty `availability_regions` (PRD §3.2's literal default), so activating any subscription for the suite's default US/CA accounts hit the PRD §3.5 region gate (`ERR_RECIPE_REGION_UNAVAILABLE`) during setup. The PRD-faithful implementation correctly rejected these — the intent that fixtures ship to the account's region was already evidenced by `setup_dispatched_shipment` passing `availability_regions=["US"]` explicitly. This makes the fixtures consistent with PRD's region-availability precondition.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_validations_and_priority.py` — `test_priority_state_beats_referential_on_activate`: removed an unnecessary `cancel_subscription` call on a DRAFT subscription. PRD §3.6 permits cancel only for `ACTIVE`/`PAUSED`/`PAST_DUE`, so the implementation correctly returned `ERR_SUBSCRIPTION_ALREADY_CANCELLED`. The cancel was incidental setup; since PRD §3.3 blocks archiving only on `ACTIVE`/`PAUSED`/`PAST_DUE` subscriptions (a DRAFT does not block), the step was both unnecessary and PRD-inconsistent. The test still validates its actual target (archived-pet state error beats retired-recipe referential error → `ERR_PET_ARCHIVED`).

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — `create_subscription`: reordered the allergen-safety check (PRD §2.9 priority 6) before the cadence-validity check (priority 8). Previously cadence was checked first, so a request with both an allergen conflict and a bad cadence returned `ERR_INVALID_CADENCE` instead of the higher-priority `ERR_ALLERGEN_CONFLICT`. PRD §2.9 verbatim orders "(6) allergen safety; ... (8) domain constraints such as cadence" with "the lower-numbered category is reported first," uniquely determining the expected outcome.

### Orchestrator verification note

The subagent's final `results.*.json` were transient and absent on exit, so the orchestrator independently re-ran the prescribed 8-round parallel sweep (`--isolation per-test-server`, correct `--start-command "cd <impl> && bash start.sh"`). All 8 rounds: **passed=77 failed=0 errors=0 total=77**. Artifacts `results.{1..8}.json` written to `workspace/implementation/`.

Note (orchestrator self-correction, no code impact): a first re-run attempt mistakenly used `--start-command "bash start.sh"` (no `cd` prefix). The runner's per-test restart hook (`pytest_plugin._restart_server` → `executor._parse_command`) resolves a `cd`-less start-command against the pytest CWD (`test_suite/`, not `implementation/`), so `start.sh` was not found and every per-test reboot failed → uniform setup ERROR on all 77 tests. This was an invocation error, not a code regression; re-running with the prescribed `cd <impl> && bash start.sh` form yielded clean 77/77 across all 8 rounds. Implementation/tests unchanged by the orchestrator.

## Step 8: Finalize PRD — 2026-06-23T04:19:13.000Z

`PRD_FINALIZED.md` created as an exact copy of `PRD.md`; after analyzing all three `<step_7_diff>` items, **no PRD edits were warranted**. Line counts: PRD.md = 306, PRD_FINALIZED.md = 306. Delta: 0 lines (0%). Files byte-identical.

Per-item analysis:
- **test_helpers/fixtures.py (`availability_regions` default)** — pure fixture bug. PRD §3.2 states the field "defaults to empty"; §3.5 mandates the region gate (`ERR_RECIPE_REGION_UNAVAILABLE`). Impl correctly enforced both. No PRD silence/mismatch. No edit.
- **test_suite/test_05 (cancel on DRAFT removed)** — pure test bug. PRD §3.6 already pins cancel only for ACTIVE/PAUSED/PAST_DUE; §3.3 blocks pet-archive only on those three states. PRD already determines this verbatim. No edit.
- **implementation/app.py (allergen check before cadence, app.py:528-533)** — impl bug fixed *into* conformance with already-pinned PRD §2.9 (allergen=cat 6, cadence=cat 8, lower-numbered reported first). Not a PRD silence. No edit.

Pre-edit search log (item 3): subject = precedence of ERR_ALLERGEN_CONFLICT vs ERR_INVALID_CADENCE at create; enumerated impl paths app.py:528-529, 531-533, 491-503 (`_run_referential_gate`), 500-501, 646 — all consistent with §2.9 fixed ordering; no PRD edit needed.

## Step 9: Complete PRD (full impl scan) — 2026-06-23T04:23:16.000Z

Base = `PRD_FINALIZED.md` (existed) → `PRD_COMPLETED.md`. Both 306 lines (all edits in-paragraph inserts). Char count 48,952 → 49,686 (+734). **3 ambiguity-pins, 0 mismatch-revisions** (impl was already well-aligned; gaps were silences, not contradictions).

Changes:
- **§2.4 The Logical Clock** — insert — ambiguity — pinned that both clock endpoints require no user-context headers and return the clock as a single `data` field `current_utc` (ISO 8601 UTC, three fractional digits) — `app.py:123,128`.
- **§3.6 Generating the next order** — insert — ambiguity — pinned that order generation imposes no logical-clock precondition (operator may generate before the clock reaches `next_order_date`); `scheduled_ship_date` is `next_order_date` at generation regardless — `app.py:707-718`, `domain.py:353`.
- **§3.9 Delivery and spoilage** — insert — ambiguity — pinned that the spoilage make-good `ReferralCredit` row sets both `referred_account_id` and `referrer_account_id` to the owning account's `id` and `beneficiary` to `REFERRED` (PRD had pinned only `referred_account_id`/status/amount) — `domain.py:486-502`.

Left unchanged (deliberate): "clock date" vs full-instant comparisons produce identical boundaries at the system's granularity (not a contradiction); referrer-grant recompute-at-grant-time and the unreachable `ERR_SELF_REFERRAL` path already consistent with existing PRD prose.

---

## Pipeline complete — 2026-06-23T04:23:16.000Z

All 9 steps complete. Final state: **77/77 tests pass across all 8 parallel rounds** (`results.{1..8}.json` in `workspace/implementation/`). Deliverables present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (9 files, 77 tests), implementation/ (Flask, in-memory, start.sh).

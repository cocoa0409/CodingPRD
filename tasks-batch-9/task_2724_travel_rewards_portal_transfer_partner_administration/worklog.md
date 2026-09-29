# Worklog — task_2724_travel_rewards_portal_transfer_partner_administration

## Step 1: Create task directory — 2026-09-04T12:16:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2724_travel_rewards_portal_transfer_partner_administration` and its `workspace/` subdirectory. Output path was pre-assigned by the invoker (index fixed by scenario number 2724); no index scan or auto-allocation was performed, per the instruction that other pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-04T13:41:00.000Z

All three scaffold artifacts are complete and the linter passes clean.

### Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2724_travel_rewards_portal_transfer_partner_administration/`)

| File | Bytes | Lines |
|---|---|---|
| `SCAFFOLD.yaml` | 160,756 | 3,193 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 104,629 | 1,727 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 197,188 | 3,200 |

### SCAFFOLD.yaml contents (§1.0–§1.7 only; contains neither design key)
15 entities, 12 state machines, 2 `concurrency_rules`, 10 calculations, 41 validations, 81 endpoints, 41 errors, 5 roles. `api_prefix: /rewards`; difficulty profile: primary `ledger_reconciliation` / secondary `posture_driven_gating`; layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`; topology flat, state-machine shape parallel, role model segregation_of_duties, consistency immediate; mandatory logical clock defaulting to `2026-08-01T00:00:00Z`.

### Design indices
- **§1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 22 instances across all 9 required `rule_id`s (2–3 differentiated instances each): dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- **§1.9 `SCAFFOLD_CORNER_DESIGN.yaml`** — 83 instances across all 9 sections: entities 13, state_machines 13, calculations 11, validations 24, endpoints 4, errors 2, rbac 7, cross_cutting_complexity_layers 8, consistency_model 1. Of those, 64 carry full `test_recipe`s and 19 are `excluded_because` stubs, each citing a named §1.8 instance (never another §1.9 instance).

### Verification
```
Coverage
  §1.5 endpoints declared:    81
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  664

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks: 105 instance names, all globally unique across both design files; every stub resolves to a real §1.8 instance and carries no `test_recipe`; all four declared complexity layers are covered in `cross_cutting_complexity_layers` (two real OCC instances matching the two `concurrency_rules` `write_endpoint`/`occ_field` pairs, one real threshold-boundary instance, five stubs); all 41 catalogued errors are cited somewhere in the design files.

Notable design decisions made while finishing the file: lint check (e) (`^expected_.+_version` must contain `${...}`) runs *before* the negative-trigger early return, so both OCC instances and the deliberately-404 error instance capture real versions and vary only the ids; every RBAC denial is named with a negative-matching suffix (`_forbidden`/`_rejected`) so the role/payload checks are legitimately skipped for the header-less and unknown-role calls, while the segregation-of-duties instance keeps a positive name and therefore gets full role/payload validation.

**Orchestrator verification:** all three files present in the task root; `workspace/` and `worklog.md` survived the subagent (checked explicitly — the scaffold step has been known to wipe the task dir).

## Step 3: Copy shared files — 2026-09-04T13:41:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). Bash-only step, no subagent.

## Step 4: Generate PRD — 2026-09-04T13:58:00.000Z

**Output:** `workspace/PRD.md` — **504 lines / 102,771 bytes**
- **Last heading:** `## 5. Error Code Catalogue`; file ends at a genuine boundary — the final table row `| ERR_SETTLEMENT_AMOUNT_INVALID | 422 |`, no mid-sentence cut.
- Built with 13 chunked `cat >>` heredoc appends plus two Python-generated tables (never a single Write), so no 64k truncation.

**Section list:** Title; §1 Introduction; §2 Global Specifications (2.1 Role-Based Access Control, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Audit Fields/Logical Clock, 2.5 Points Arithmetic & Pinned Rounding Order, 2.6 Optimistic Concurrency on Offers and Accounts, 2.7 The Points Ledger and the Conserved Quantity, 2.8 Request Admission Order, 2.9 Cascade Semantics and Version Propagation, 2.10 The Deterministic Sweep); §3 Business Logic & Workflows (3.1 Accounts; 3.2 Merchant Classification & Rotations; 3.3 Posting a Purchase; 3.4 Reversal Four-Hop Clawback; 3.5 Portal Inventory, Markup & Parity; 3.6 Redemption Quote→Confirm→Ticket→Settle; 3.7 Partner Agreements & Bonus Events; 3.8 The Transfer Pipeline; 3.9 Fraud Controls, Posture & Benefits; 3.10 Change Notices & Grandfathering; 3.11 Liability & Breakage); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage confirmed mechanically against SCAFFOLD.yaml:**
- **81/81 endpoints** — §4 table has exactly 81 rows, every `method + path` pair matched with description and authorized roles; 0 missing.
- **15/15 entities** — all **158** `entities[].fields[].name` identifiers present verbatim in backticks; 0 missing.
- **41/41 errors** — all error IDs appear in §3 prose *and* §5, with every `error_id`/`http_status` pair matching the scaffold exactly; 0 mismatches.
- Endpoint `input` identifiers: 98/98 present. Roles: 5/5. State-machine states (12 machines): 33/33. All non-enum caps constants accounted for in prose (`MCC` as "merchant category code", `ASC` as ascending order, `STATEMENT_CREDIT_CENTS_PER_POINT` as "one cent per point").

**Hard Contract reports (agent message only, never written into the PRD or a sibling file):**
- **Contract 1 — Field-Name Coverage: PASS.** entities 158/158, endpoint inputs 98/98, 0 missing.
- **Contract 2 — Rule Coverage: PASS.** 41-step admission ladder in §2.8 with every error ID + status + scope; both OCC rules (`expected_offer_version` → `ERR_STALE_OFFER_VERSION` 412, `expected_account_version` → `ERR_STALE_ACCOUNT_VERSION` 412); all 12 machines' transitions with preconditions and side-effects; all four multi-hop cascades hop by hop; all 10 calculations as prose with constants embedded; sibling branches treated symmetrically (CONFIRMED/CLEARED, LOCKED→CLEAR/LOCKED→WATCH, QUOTED-cancel/CONFIRMED-cancel, provisional/final cost, COST_BASIS/FAIR_VALUE, MAPPED/FALLBACK).
- **Contract 3 — §3 Path Purity: PASS.** 1,153 backtick tokens scanned in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path.

**Fixes applied this pass** (four gaps found by the verifier, all now closed): `TERMINATED` state name and the `SUSPENDED` → `TERMINATED` pair added in §3.7; the four-operation `ERR_AGREEMENT_NOT_ACTIVE` scope enumerated in §3.8; the seven-operation `ERR_ACCOUNT_POSTURE_LOCKED` gate enumerated in §3.9 (plus the explicit note that `WATCH` gates none); the null/zero creation defaults for `issuer_cost_final_cents`, `cost_per_1k_final_cents`, `invoice_amount_cents`, `ticketed_at`, `settled_at`, `closed_reason`, `pnr_locator`, `settlement_adjustment_cents` and the `base_units`/`bonus_units`/`partner_units_credited` zeros on a new transfer request.

**Integrity:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point. Greps confirm PRD.md contains no occurrence of "harder than expert", "Generate task", "difficulty", "test_recipe", or any scaffold section reference. §2.2 was produced by `cat`-ing the canonical `section-2.2-response-structure.md` and diffs clean.

**Orchestrator truncation check (mandated by invoker):** independently ran `wc -l -c`, `grep -n '^#' | tail -12`, and `tail -12` on PRD.md. The file's final heading is `## 5. Error Code Catalogue` and the last line is a complete markdown table row. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T14:35:00.000Z

Smoke server shut down by port; `__pycache__` cleaned. The implementation is complete.

### Files written

All under `workspace/implementation/` — 28 files, 3,830 lines total, flat module layout, Flask 3 + stdlib only.

| Layer | Files (lines) |
|---|---|
| Launcher | `start.sh` (10, chmod +x, guarded pip so per-test reboots skip install), `requirements.txt` (1) |
| Kernel | `core.py` (302) in-memory `DB`, logical clock, ISO-8601 3-digit formatting, `new_row`/`store`/`touch`/`ordered`, Decimal rounding helpers, envelope + pagination; `errors.py` (65) all 41 error IDs → HTTP status; `auth.py` (100) header ladder, `@endpoint(roles)`, ownership/agency-scope/SoD guards; `shapes.py` (217) body coercion/validation; `rhelp.py` (83) the shared state and fiscal guards; `views.py` (65) serializers + `listing()`; `app.py` (82) blueprint wiring and error handlers |
| Services | `svc_ledger.py` (161), `svc_posture.py` (196), `svc_pricing.py` (112), `svc_transfer.py` (77), `svc_earn.py` (102), `svc_liability.py` (122), `svc_notice.py` (41), `svc_sweep.py` (97) |
| Routes | `r_clock.py` (32), `r_accounts.py` (89), `r_catalog.py` (170), `r_transactions.py` (160), `r_agency.py` (296), `r_orders.py` (266), `r_agreements.py` (277), `r_transfers.py` (237), `r_fraud.py` (238), `r_notices.py` (173), `r_liability.py` (59) |

**Endpoint count: exactly 81**, enumerated from the live URL map and matched one-for-one against PRD §4 (3 ops/clock, 4 accounts, 7 catalog, 6 transactions+ledger, 12 agency+offers, 8 orders, 13 agreements+bonus events, 8 transfers, 10 fraud+entitlements, 7 notices, 3 liability).

### How it is organised

- **State machines** live in the route modules, each transition funneled through `rhelp.require_state(row, allowed, field)` so `ERR_INVALID_STATE_TRANSITION` is uniform; the two parallel dimensions (order `fulfillment_status`×`settlement_status`, account `status`×`fraud_posture`) are independent fields that no transition cross-writes. Derived machines are elsewhere: `svc_posture.derive_posture` runs the 4 ordered tests plus the 4 asymmetric cascades, and `svc_sweep.run_sweep` executes the 8 pinned steps.
- **Calculations** are isolated per domain so the pinned rounding orders can't drift: `svc_earn` (independently floored earn legs, rotation headroom), `svc_transfer` (per-1,000-block floor then sum), `svc_pricing` (ceil cash→points, half-up cents), `svc_liability` (7 sequential steps, buckets rounded before summing).
- **Validation** is layered to reproduce §2.8's 11-tier order: `auth` (tiers 1-4) → `shapes`/`pagination` (tier 5) → `rhelp` (tier 6 state/lifecycle) → OCC version checks → domain/temporal/referential/fiscal checks inline per route. `core.touch()` is idempotent per row per request, so §2.9 cascades that revisit a row still yield exactly one version bump.

### Smoke-test results

Two scripted end-to-end passes on `PORT=18724`, **58 + 96 = 154 assertions, all passing**, spanning every domain and both success and 4xx paths (401 missing/unknown header, 403 role/ownership/agency-scope/SoD, 402 insufficient points, 412 both stale-version codes, 409 state/posture/parity/duplicate/seat, 422 fiscal/referential, 404 unknown path, 400 pagination), plus arithmetic spot-checks (per-block floor 5994 and 498 units, 83520-point burn, 1130/1011 cost-per-1k, rotation headroom 50000, breakage tier 1200 bps).

Two real defects were found and fixed:
1. **`POST /redemption-orders/{id}/ticket` never set `fulfillment_status = "TICKETED"`** — it only moved `settlement_status`, which made settle/refund permanently unreachable (409 on the fulfillment guard). Fixed in `r_orders.py`.
2. **`recompute_seats()` could flip OPEN→SOLD_OUT during a pre-check** without a version bump; refactored to return a boolean so the caller owns the bump, and the three pre-check sites now use `count_committed()`.

Everything else that looked like a failure turned out to be a wrong expectation in my throwaway test script, verified against the PRD each time: benefit errors are 409 (not 422), a SOLD_OUT offer yields `ERR_OFFER_NOT_BOOKABLE` before the seat check, `ratio_*_applied` stays null until completion, `grandfather_expires_at` is deliberately retained after maturation, two holds put an account permanently at WATCH, and `gross_outstanding_points` is an unclamped ledger sum (legitimately negative after a clawback). The 41 error IDs and their statuses were diffed programmatically against the PRD table — exact match, no extras, no omissions.

Fresh-boot behaviour verified for the `--isolation per-test-server` harness: **0.61 s** to first served request, all 15 collections report `total_count=0`, clock defaults to `2026-08-01T00:00:00.000Z`, and no file/SQLite/tmp artifacts are created. `__pycache__` was removed and the smoke server was killed by port 18724 only. `worklog.md`, `test_helpers/`, `test_suite/`, and the two design YAMLs were never read or written.

**Orchestrator note:** Steps 5 and 6 were launched back-to-back as the two most recent messages rather than as two tool uses inside one message. Physical isolation was preserved regardless — the impl generator was additionally given an explicit hard constraint never to read `test_helpers/`, `test_suite/`, or the two design YAMLs, and it confirms it never did; `test_suite/` did not yet exist on disk when it started (first test file appeared at 14:08, impl work began at ~14:03).

## Step 5: Generate unit tests — 2026-09-04T15:12:00.000Z

Test generation for task 2724 is complete. Everything sits at the task root; nothing was written under `workspace/` and `worklog.md` was not touched.

**test_helpers/ (9 modules, 2637 lines)**
`api_client.py` 665, `fixtures.py` 604, `factories.py` 505, `assertions.py` 262, `types.py` 223, `constants.py` 153, `api_errors.py` 126, `test_users.py` 82, `__init__.py` 17. ISO-8601 sub-second precision is canonicalised inside `api_client.py` (via `assert_timestamp_equals`/normalisation), never asserted on raw string width in tests.

**test_suite/ (conftest + 19 files, 6297 lines, 122 tests)**
conftest 30/0 tests; test_01 275/5, test_02 324/6, test_03 256/5, test_04 301/5, test_05 220/5, test_06 241/7, test_07 340/7, test_08 380/7, test_09 254/5, test_10 244/7, test_11 262/6, test_12 308/6, test_13 399/8, test_14 545/10, test_15 433/8, test_16 367/8, test_17 395/5, test_18 366/7, test_19 387/5. Every file now holds at least 5 tests.

**Per-queue coverage**
- Queue A (§1.8 Difficulty): 22/22 instances translated, 0 skipped, 52 tests, every instance carrying ≥2 tests.
- Queue B (§1.9 Corner): 83 instances in the file, 64 non-stub (19 carry `excluded_because` and are deferred to §1.8); 63/64 non-stub translated, 70 tests.

**Skipped instances (1)**
- `Corner/errors/every_catalogued_error_is_reachable_across_the_two_design_files` — a meta-audit of the two design YAMLs, not an API behaviour; the PRD derives no observable outcome for it.

**Verification (all green)**
- Design-tag pass: 122 tests, 0 untagged, 0 dual-tagged, 0 unresolvable tags, 85 distinct instances, tags byte-matched against names parsed out of both YAMLs.
- Verbatim-citation pass: 138 quoted PRD fragments, 0 misses, every test carries at least one quote.
- `python3 -m pyflakes test_suite/*.py test_helpers/*.py` exits 0; every module imports cleanly; `__pycache__` directories removed.

Notable PRD-over-design corrections carried through the suite: `seats_committed` (not `portal_seats_committed`), offer `status` OPEN/SOLD_OUT (not `availability_status`), `cash_copay_cents`, `inventory_offer_id`, `points_pending_redemption`; `available_points` treated as the computed §2.7 concept rather than a field; and three design figures replaced by PRD-derived ones (consistency-model 8000 → 7500; transfer balances 10000/2000 → 9000/1000 then 8000/2000).

**Orchestrator verification:** `find workspace -type d -name 'test_*'` returns nothing — no stray `test_helpers/`/`test_suite/` landed under `workspace/`, so Step 7 can run against the task-root dirs directly. Only one `worklog.md` exists (the task-root one).

## Step 7: Run tests and iterate — 2026-09-04T15:40:00.000Z

Clean 8-round sweep. Done.

**Iterations run:** 2

**Iteration 1** — all 8 rounds: 121/122, the same single test failing in every round (deterministic, not flakiness, not load):
- `test_04_transitive_cascades.py::test_the_clawback_hop_drives_the_balance_negative_and_spares_the_other_purchase`
- Failure detail: `AssertionError: Expected lifetime_points_earned == 5000, got 10000`

**Tests deleted:** none. No test failed the STEP 1 coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_transitive_cascades.py`, in `test_the_clawback_hop_drives_the_balance_negative_and_spares_the_other_purchase` — the `assert_account_aggregates` expectation `lifetime_points_earned=5000` was corrected to `10000` (comment added citing the PRD sentence).

**Diagnosis (STEP 2, assertion mis-translation):** the test read §3.4's compressed clause "*the account's `points_balance` is recomputed from the ledger and falls by `total_points_earned`, and `lifetime_points_earned` is recomputed as well*" as meaning the clawback *reduces* the lifetime-earned aggregate. But §2.7 states the aggregate's formula verbatim and exhaustively: "*Its `lifetime_points_earned` is the sum of `points_delta` over entries whose `entry_type` is `EARN_BASE` or `EARN_BONUS`.*" A `CLAWBACK` entry is neither type, so *recomputing* the aggregate after a reversal legitimately still returns both 5,000-point earn legs, i.e. 10,000. `workspace/implementation/svc_ledger.py::lifetime_earned` implements that formula exactly (`entry_type in EARN_TYPES`), so this was a test bug, and correcting the expected value makes the test *more* faithful to PRD rather than less. The test's other assertions (CLAWBACK entry with `points_delta=-5000`/`balance_after=-3000`, `points_balance=-3000`, `points_pending_redemption=8000`, the first purchase left `POSTED`) are all verbatim-covered and were left intact.

**Final per-round figures (iteration 2), quoted from `workspace/implementation/results.$i.json`:**

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 122/122 | 0 | 0 | 0 |
| 2 | 122/122 | 0 | 0 | 0 |
| 3 | 122/122 | 0 | 0 | 0 |
| 4 | 122/122 | 0 | 0 | 0 |
| 5 | 122/122 | 0 | 0 | 0 |
| 6 | 122/122 | 0 | 0 | 0 |
| 7 | 122/122 | 0 | 0 | 0 |
| 8 | 122/122 | 0 | 0 | 0 |

All eight `results.*.json` files exist on disk and parse as complete JSON. `worklog.md` was not touched.

**Orchestrator verification:** independently re-read all 8 `results.*.json` with a JSON parser — every round reports `passed=122, failed=0, errors=0, skipped=0, total=122`. The artifacts are on disk (≈40 KB each), so the clean sweep is real and not a subagent claim without evidence.

**Step 8 decision:** the skip condition (0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes) is NOT met — there was one `test_suite/` fix. Step 8 therefore runs. Note that the single fix was an assertion mis-translation resolved *in the PRD's favour* (§2.7 already pins the formula verbatim, and the implementation already matched it), so a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome here; Step 9 is the step that must not be identical.

## Step 8: Finalize PRD — 2026-09-04T15:46:00.000Z

`PRD_FINALIZED.md` is written. Chose option **(a)**: one small clarifying revision of §3.4's second-hop clause, and nothing else.

### Line counts
- `PRD.md`: 504 lines; `PRD_FINALIZED.md`: 504 lines. Line-count delta 0 (+0.0%); one line revised in place (1/504 = 0.2% of lines touched). Byte size 102,771 → 102,989.

### Changes
- **§3.4 (second hop of the clawback cascade)** — *revise* — kept the existing sentence verbatim and appended a clause pinning that the recomputation of `lifetime_points_earned` runs the §2.7 formula (only `EARN_BASE` + `EARN_BONUS` `points_delta`), so a `CLAWBACK` entry is not in that sum and the aggregate comes back **unchanged** — `implementation/svc_ledger.py:54-59` (`lifetime_earned`, `entry_type in EARN_TYPES`), reached via `svc_ledger.py:94` (`refresh_account`) from `r_transactions.py:120,137`.

### Pre-edit search log (the one edit)
- **(a) Subject identified:** which account aggregates a `CLAWBACK` ledger entry moves when the purchase-reversal cascade "recomputes" them — i.e. the recomputation semantics of the four §2.7 ledger aggregates on a reversal.
- **(b) Impl paths enumerated (grepped `lifetime_points_earned|lifetime_earned|lifetime_points_redeemed|lifetime_redeemed|CLAWBACK` across all of `implementation/`, then read each hit):**
  - `svc_ledger.py:50-51` `points_balance` — sums `points_delta` over *all* entries, so the clawback does lower the balance by `total_points_earned` (existing prose stays true).
  - `svc_ledger.py:54-59` `lifetime_earned` — `EARN_TYPES = ("EARN_BASE","EARN_BONUS")` only; `CLAWBACK` excluded → unchanged. Sole producer of `lifetime_points_earned`.
  - `svc_ledger.py:62-68` `lifetime_redeemed` — `DEBIT_TYPES = ("REDEEM_DEBIT","TRANSFER_DEBIT")`; `CLAWBACK` also excluded here, so the clawback moves neither lifetime aggregate.
  - `svc_ledger.py:79-96` `refresh_account` / `pending_redemption` — the single recomputation entry point; `points_pending_redemption` is derived from `QUOTED` orders + `SUBMITTED/HELD/QUEUED` transfers, so hop three's `SUBMITTED|QUEUED → HELD` moves stay inside the pending set and the aggregate is untouched by the clawback.
  - `svc_ledger.py:26-44` `append_entry` — the only writer of ledger rows; calls `_recompute_balances` + `refresh_account`, i.e. *every* entry type recomputes all four aggregates the same way, so no parallel producer of `lifetime_points_earned` exists off the Step 7 site.
  - `r_transactions.py:96-138` — the reversal endpoint; hops one/two/three/four as read, `refresh_account` called at :120 and :137.
  - `r_accounts.py:27-28` — enrolment seeds both lifetime aggregates at 0; consistent.
  - `r_transfers.py:34` — `INSUFFICIENT_BALANCE_AFTER_CLAWBACK` is only a `hold_reason` enum member, not an aggregate path; no bearing on the wording.
  - Cross-checked the two other PRD sentences on the same subject: §2.7's formula and §3.3's "`points_balance` and `lifetime_points_earned` rise accordingly" — the new clause is consistent with both.
- **(c) Wording adjustment made:** scoped the claim to the `CLAWBACK` entry's contribution to that one sum ("does not enter that sum and comes back unchanged") rather than writing anything like "the reversal changes no aggregate but the balance". The broader phrasing would have been a false universal — hop three's holds and hop four's posture cascade do move other rows/fields — so the sentence deliberately makes no closed-world statement about the rest of the hop. The original clause is left byte-identical up to the em dash so pre-existing prose is not re-litigated.

Note on the Step 7 item itself: it was a genuine test-side mis-translation (impl unchanged, no fixture bug), and §2.7 + §3.4 arguably already determined the value. The revision is therefore purely a de-ambiguation of a compressed clause that a careful reader demonstrably misread; it adds no behavior.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line, in §3.4, matching the reported edit. Both files are 504 lines.

## Step 9: Complete PRD — 2026-09-04T16:38:00.000Z

Step 9 was deliberately run as **four sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`**, rather than a single scan. A one-shot Step 9 over a 28-module implementation reliably degenerates into a shallow skim (its tell is a `PRD_COMPLETED.md` byte-identical to `PRD_FINALIZED.md`, meaning the scan never really ran). Pass 1 owned the `cp`; passes 2, 3, and 4 were explicitly forbidden from copying, so no pass could clobber its predecessors' edits. Each pass was told which subjects earlier passes had already pinned so the passes would not collide on the same sentences.

**Final result: `workspace/PRD_FINALIZED.md` 504 lines / 102,989 chars → `workspace/PRD_COMPLETED.md` 504 lines / 115,871 chars (+12,882 chars, +12.5%), 98 diff lines, 55 edits, 0 new lines/sections — every edit is an in-paragraph insert or revision.**

Aggregate counts across the four passes: **41 ambiguity-pins, 13 mismatch-revisions, 1 verified no-change-needed.**

### Pass 1 — kernel + early routes (`core.py`, `errors.py`, `auth.py`, `shapes.py`, `rhelp.py`, `views.py`, `app.py`, `start.sh`, `r_clock.py`, `r_accounts.py`, `r_catalog.py`, `r_transactions.py`)
504 lines / 102,989 → 107,507 chars (+4,518). 18 ambiguity-pins, 2 mismatch-revisions.
- §2.1 — revise — ambiguity — whitespace-only auth header counts as empty → `ERR_MISSING_AUTH_HEADERS` — `auth.py:29`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars — `core.py:233,236`
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, never the logical clock — `core.py:120,241`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION`; empty-string value = omitted — `core.py:284-297`
- §2.3 — insert — ambiguity — list tie-break for equal `created_at` is server insertion order — `core.py:185-188`
- §2.3 — insert — ambiguity — filters are exact equality (unknown enum matches nothing, empty string ignored); boolean spellings `true/1/yes` vs `false/0/no`, others ignored; unnamed query params ignored — `shapes.py:200-217`, `views.py:45-55`
- §2.4 — insert — ambiguity — every client-supplied instant canonicalised to UTC with exactly 3 fractional digits on store/echo — `core.py:82-117`
- §2.4 — revise — ambiguity — clock setter requires `current_utc`, accepts backwards moves, returns 200 with `data` = single `current_utc` field (not a row); reader same shape — `r_clock.py:14-26`
- §2.7 — insert — ambiguity — ledger ordering falls back to insertion order when `occurred_at` and `created_at` both tie (EARN_BASE before EARN_BONUS) — `svc_ledger.py:14-16`, `r_transactions.py:160`
- §2.8 step 4 — insert — ambiguity — absent body = empty object; malformed/non-object JSON → `ERR_INVALID_REQUEST`; explicit `null` ≡ omission; integer fields accept integral JSON numbers but never booleans/numeric strings; decimals reject strings/booleans — `shapes.py:16-24,53-134`, `app.py:57-63`
- §2.9 — insert — ambiguity — `version` increments once per row per request, not once per hop — `core.py:168-182`
- §2.9 — **revise — mismatch** — cascade/sweep tie-break is insertion order, **not `id` ascending** — `core.py:185-188`
- §3.1 — insert — ambiguity — `email` unvalidated beyond non-empty string; `enrolled_at` not compared to the clock — `r_accounts.py:42-46`
- §3.1 — revise — ambiguity — account reads recompute the four ledger aggregates but never re-derive posture and never touch `updated_at`/`version`; applies to list pages — `views.py:24-27`, `r_accounts.py:51-70`
- §3.2 — insert — ambiguity — `base_multiplier` stored/echoed verbatim, not normalised — `r_catalog.py:52`
- §3.2 — insert — ambiguity — `bonus_multiplier` echoed verbatim; `window_end` ≤ `window_start` → `ERR_INVALID_REQUEST` (400), not a temporal error — `r_catalog.py:95-96,125`
- §3.2 — insert — ambiguity — publishing a rotation whose `window_start` ≤ clock → `ERR_INVALID_STATE_TRANSITION` (409) — `r_catalog.py:162-166`
- §3.3 — insert — ambiguity — degenerate no-mapping/no-fallback case still sets `classification_source` = `FALLBACK` — `svc_earn.py:31`
- §3.3 — **revise — mismatch** — `EARN_BASE` entry appended even when `base_points` is 0 (delta 0), so "positive `points_delta`" was wrong — `r_transactions.py:54-61`
- §4 intro — insert — ambiguity — unknown path or undefined method → `ERR_RESOURCE_NOT_FOUND` (404), trailing slash insignificant — `app.py:46,57-62`

Pass 1 also mechanically verified §5's catalogue against `errors.ERROR_STATUS` (41/41 exact, no id or status divergence) and §4's paths/roles against its partition's blueprints — no edits needed there.

### Pass 2 — service modules (`svc_ledger.py`, `svc_posture.py`, `svc_pricing.py`, `svc_transfer.py`, `svc_earn.py`, `svc_liability.py`, `svc_notice.py`, `svc_sweep.py`)
107,507 → 111,005 chars (+3,498). 10 ambiguity-pins, 7 mismatch-revisions. No `cp` run; pass 1's hunks verified intact.
- §2.7 — insert — ambiguity — `balance_after` is a running figure recomputed across the whole ledger on every append, so an entry appended at an earlier `occurred_at` (clock moved backwards) rewrites the `balance_after` of entries that now follow it — `svc_ledger.py:19-23,42`
- §2.10 — insert — ambiguity — each sweep step re-selects by current status, so one sweep can advance a row twice (rotation activates in step 1 and expires in step 2, counting in both counters; event opens in step 3 and closes in step 4) — `svc_sweep.py:27-60`
- §2.10 — revise — mismatch — "every row the sweep touches bumps `version`" → every row the sweep *transitions*; an account whose aggregates are merely refreshed by a step-7 completion is not bumped — `svc_sweep.py:86`
- §3.3 — revise — mismatch — rotation-cap accumulator compares the `(created_at, insertion order)` pair, so a same-instant earlier-inserted `POSTED` purchase does count — `svc_earn.py:51-67`
- §3.5 — revise+insert — mismatch+ambiguity — sold-out trip is `seats_committed >= portal_seats` (not "before plus one equals"); the cycle moves only `OPEN`↔`SOLD_OUT`; on a seat release only a status move bumps the offer's `version` — `svc_ledger.py:123-138`
- §3.6 — insert — ambiguity — points rounding is toward positive infinity, so a copay meeting/exceeding `portal_price_cents` gives `points_debited` of 0 or negative rather than an error; `points_requested` stays null on `PORTAL_BOOKING` — `svc_pricing.py:62-72,93`
- §3.6 — insert — ambiguity — `confirmed_at` added to the "null on every newly created order" list — `svc_pricing.py:108`
- §3.8 — revise — mismatch — sweep completion bumps only the request's `version`; the account's does not move — `svc_sweep.py:82-87`
- §3.8 — revise — mismatch — `transfer_increment_points` is not constrained to a multiple of 1,000, so a remainder below a full block is dropped and earns no units despite being debited — `svc_transfer.py:32-34`, `r_agreements.py:46-47`
- §3.8 — revise — ambiguity — per-block units named explicitly as 1,000 × `ratio_partner_units_in_applied` ÷ `ratio_points_out_applied` — `svc_transfer.py:26-28`
- §3.9 — insert — ambiguity — a posture recomputation landing on the posture already carried runs no cascade and does not refresh `updated_at`/`version` — `svc_posture.py:165-170`
- §3.9 — insert — ambiguity — recovery branch is keyed on destination posture: any movement into `CLEAR` (from `LOCKED` *or* `WATCH`) reinstates every `SUSPENDED` entitlement; only `LOCKED`→`WATCH` takes the second branch — `svc_posture.py:173-180`
- §3.10 — insert — ambiguity — every `ACTIVE` account the effective-notice walk visits is touched (version +1), including one whose grandfathering triple is unchanged — `svc_notice.py:14-24`
- §3.10 — revise — mismatch — "the second phase runs on a later sweep" → it is step 6 of every sweep, and an already-matured window is promoted by the same sweep that made the notice effective — `svc_sweep.py:63-69`, `svc_notice.py:28-41`
- §3.11 — insert — ambiguity — step two walks every account regardless of `status`, closed ones included — `svc_liability.py:40-46`
- §3.11 — insert — ambiguity — the dormancy test ignores earn entries after `as_of`, so a later earn never rescues an account from dormancy at that cut-off — `svc_liability.py:26-37`
- §3.11 — revise — mismatch — blended-cost fallback to 1000 fires when the summed `points_debited` divisor is zero, not merely when the input set is empty — `svc_liability.py:84-85`

### Pass 3 — remaining routes (`r_agency.py`, `r_orders.py`, `r_agreements.py`, `r_transfers.py`, `r_fraud.py`, `r_notices.py`, `r_liability.py`)
111,005 → 115,477 chars (+4,472). 13 ambiguity-pins, 4 mismatch-revisions. No `cp` run; passes 1–2 verified intact by sentinel grep (8/8 distinctive phrases, each exactly once).
- §2.6 — insert — ambiguity — `expected_offer_version`/`expected_account_version` are integers ≥ 0, so a negative/fractional/string/boolean value is `ERR_INVALID_REQUEST` at §2.8 step 4, not a 412 — `r_agency.py:271`, `r_transfers.py:53`
- §3.5 — insert — ambiguity — `invoice_terms_days` must be at least 0 — `r_agency.py:61`
- §3.5 — insert — ambiguity — resync's four fields are all required and the only ones read (no `tax_cents`, so `cash_copay_cents` never moves); no origin-state and no agency-status precondition; it never writes `status` or `seats_committed` — `r_agency.py:187-207`
- §3.5 — insert — ambiguity — `seats_committed` is recomputed and returned on every read and list row with no `updated_at`/`version` change; reinstate, withdraw and book recompute it before their seat tests — `views.py:41`, `r_agency.py:229,247,282`
- §3.6 — revise — **mismatch** — `points_requested` is an integer ≥ 1, so 0/negative is `ERR_INVALID_REQUEST` and only 1–2,499 reaches `ERR_STATEMENT_CREDIT_BELOW_MINIMUM`; also pinned that the field is required only on `STATEMENT_CREDIT` — `r_orders.py:54,64`
- §3.6 — insert — ambiguity — `cents_per_point_applied` is still pinned from `card_product_code` on the statement-credit channel even though it does not enter the arithmetic — `svc_pricing.py:76-77`
- §3.6 — insert — ambiguity — an offer status outside `OPEN`/`SOLD_OUT` refuses confirmation with `ERR_OFFER_NOT_BOOKABLE` — `r_orders.py:110`
- §3.6 — insert — ambiguity — a non-`PORTAL_BOOKING` order is refused ticketing with `ERR_INVALID_STATE_TRANSITION`, and agency-scope comparison is skipped on an order with no offer behind it — `r_orders.py:175,178`
- §3.7 — insert — ambiguity — reinstatement leaves `submitted_by_user_id`/`approved_by_user_id` as originally recorded — `r_agreements.py:152-162`
- §3.7 — insert — ambiguity — bonus-event `window_end` at or before `window_start` is `ERR_INVALID_REQUEST` (400), not a window conflict — `r_agreements.py:199`
- §3.8 — revise — ambiguity — "unresolved until completion" → both applied-ratio fields are **null** until completion — `r_transfers.py:88-89`
- §3.9 — insert — ambiguity — entitlement `expires_at` is never compared against the clock at grant time; a past instant is accepted and waits for the sweep — `r_fraud.py:147`
- §3.9 — revise — **mismatch** — consume runs its checks in §2.8 order (closed → locked → `BENEFIT_NOT_CONSUMABLE` → ticketed-booking → order mismatch → allowance last), not with the allowance check third — `r_fraud.py:202-230`
- §3.9 — insert — ambiguity — case reads and list rows re-derive `risk_score` from current `status` with no `updated_at`/`version` change — `views.py:35-37`, `r_fraud.py:67,79`
- §3.10 — insert — ambiguity — `target_agreement_id`/`supersedes_notice_id` resolve ahead of every other shape check (404 wins over a missing required field), and an absent/null/empty/non-string value is stored as null rather than rejected — `r_notices.py:35-44`
- §3.10 — revise — **mismatch** — submit runs the agreement-`ACTIVE` test first when a target is present (per §2.8), reporting `ERR_NOTICE_TARGET_REQUIRED` only when the target is null — `r_notices.py:110-123`
- §3.11 — insert — ambiguity — exact persisted snapshot field list (`id`, `created_at`, `as_of`, `method`, `generated_by_user_id`, seven figures); the selected breakage rates are not persisted — `r_liability.py:29-46`

### Pass 4 — closing the two gaps pass 3 flagged as falling between partitions
115,477 → 115,871 chars (+394). 1 ambiguity-pin, 1 verified no-change-needed. **Orchestrator's decision to run this pass:** pass 3's hand-off explicitly named two behaviours it had left unpinned because their primary subject sat in another pass's partition. Leaving them would have contradicted Step 9's whole purpose (zero residual silence), so a fourth, deliberately narrow pass was spawned rather than accepting a known gap.
- **Item 1 — `svc_transfer.resolve_ratio`'s extra non-null/non-zero guard on the replacement ratio fields: NO CHANGE NEEDED (verified, not assumed).** The guard is unreachable defensive code, so pinning it would assert a state no caller can construct: the only writer of those fields is `create_notice` via `opt_int(..., minimum=1)` (`r_notices.py:48-49,69-70`), so any non-null value is already ≥ 1; there is no notice-update endpoint, so neither the ratio fields nor `change_type` can be mutated after creation; and the only route to `EFFECTIVE` is sweep step 5 over `ANNOUNCED` notices, which requires passing `submit_notice` (`r_notices.py:113-122`), which already rejects a `TRANSFER_RATIO_CHANGE` with a null target or either null ratio term. Every `EFFECTIVE` ratio-change notice therefore necessarily carries both terms non-null and ≥ 1, and the PRD's existing four-condition enumeration plus its "in every other case" fallback already uniquely pins all reachable behaviour.
- §3.7 — insert — ambiguity — `settlement_cost_cents_per_1k` is validated, stored, and returned on reads but consumed by **no** calculation: transfer completion derives units from the applied ratio pair alone and records no cash figure, and §3.11's blended cost is drawn exclusively from redemption orders — `r_agreements.py:51` (sole site, confirmed by exhaustive grep of both the field name and the bare stem `settlement`), corroborated by `svc_transfer.py:29-42` and `svc_liability.py:62-86`. The PRD's "being the cash the issuer pays the partner for every 1,000 points transferred" had implied a downstream consumer that does not exist.

### Orchestrator verification of the final artifact
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — the scan genuinely ran (an identical file is the known failure signature of a skipped Step 9).
- 504 lines, 115,871 chars; all 5 top-level `## ` sections present; final heading `## 5. Error Code Catalogue`; file ends on the complete table row `| ERR_SETTLEMENT_AMOUNT_INVALID | 422 |` — no truncation.
- 98 diff lines vs `PRD_FINALIZED.md`, zero line-count change, zero new sections — consistent with the minimal-in-paragraph-patch contract.
- Every pass reported that it read no `SCAFFOLD*.yaml` and never touched `worklog.md`, `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/`, or `test_helpers/`.

**Pipeline complete.** All nine steps finished; the final 8-round sweep stands at 122/122 in every round.

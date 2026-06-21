# Worklog — task_0251_public_library_management

## Step 1: Create Task Directory — 2026-06-08T11:36:29.000Z

Created `tasks/task_0251_public_library_management/` with `workspace/` subdirectory. Pre-allocated path used directly (no ID scan). Verified `./INSTRUCTION.md` and `./skills/` present.

## Step 2: Generate Scaffold (Expert band) — 2026-06-08T11:59:54.000Z

All three scaffold artifacts are generated and pass the linter clean. Here is the verbatim verdict block from `scaffold_lint.py`:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated the Expert-band scaffold for **Public Library Management** (task_0251) — three files written:

**Profile**: primary archetype quota_allocation + secondary temporal_windowing; flat topology; cyclic state-machine shape; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities**: Branch, Patron, Title, Copy, Loan, Hold, Reservation, BookableResource, IllRequest, LicensePool, EbookLoan, Fine (19 FKs, all with reverse-reachability GETs).
- **8 state machines**: Loan (cyclic renewal self-loop + LOST/RETURNED), Hold (queue promotion loop WAITING→READY→FULFILLED/EXPIRED), Reservation (branching CONFIRMED→{CHECKED_IN,NO_SHOW,CANCELLED}), EbookLoan, IllRequest, Fine, plus system-driven Copy and Title machines. One concurrency rule (OCC on BookableResource.version for reservation creation, ERR 412).
- **8 calculations** incl. 3 variant families: overdue fine (chronological final vs forward-looking estimate), lost-item replacement charge (depreciated vs flat, pinned round-each-component-then-sum), capped account balance (pinned waiver-tier eval order), plus room/computer overlap, hold-queue position, license availability, patron balance/block.
- **12 validations** (ordered priority 1–12), **20 errors**, **3 RBAC roles** (Patron entity_backed; Librarian & BranchManager opaque). **58 endpoints** — above the 20–32 guideline, driven by required single-resource + filtered-list GETs for all 12 entities (testability-completeness overrides count per §1.5).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules covered, **19 instances** (≥2 each; combinatorial_formula has 3 spanning modes a/b/c). Each instance differentiated across distinct entity domains / error-category pairs / interval semantics / conserved quantities. All formula-derived asserts pre-computed to literals (e.g., overdue 150c vs estimate 100c; replacement 3000c vs 3300c; cap 1000c; license/copy conservation invariants).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** breadth probe across all 9 claim-extraction sections — **33 active instances + 3 excluded_because stubs** citing §1.8 instances.

**Verification performed**: YAML parse of all three; FK reverse-reachability simulation (fixed one gap on Hold.ready_copy_id); all §1.8/§1.9 grounds resolve into §1.1–§1.7; enum-value closure; no forbidden concurrency vocabulary; no id-in-decision; OCC contract; unique instance names; date/formula arithmetic re-derived in Python.

Files: SCAFFOLD.yaml (1452 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1084 lines), SCAFFOLD_CORNER_DESIGN.yaml (1221 lines).

## Step 3: Copy Shared Files — 2026-06-08T12:00:18.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-08T12:06:19.000Z

Generated `workspace/PRD.md` for the Public Library Management API (EXPERT-band scaffold, 12 entities, 8 state machines, 7 calculations, 12 validations, 58 endpoints, 20 errors).

**Document stats:**
- Line count: 288
- Section count: 5 top-level (`## 1`–`## 5`) with 21 H3 subsections — 11 in §2 (domain-derived cross-cutting principles) and 10 in §3 (business workflows grouped by lifecycle)
- §4 endpoint table: 58 rows, 4 columns (Method, Path, Description, Authorized Role)
- §5 error table: 20 rows, 2 columns (Error ID, HTTP Status)

**Hard Contracts — all PASS:**
- **Contract 1 (Field-Name Coverage):** 67 required field names present, 0 missing.
- **Contract 2 (Rule Coverage):** All 20 error IDs surface in §1–§4 narrative. OCC rule expresses write endpoint + `expected_resource_version` + `version` mismatch + `ERR_STALE_RESOURCE_VERSION`/412. All 12 validation priorities stated as explicit ordering (§2.10). Cascades (check-in→hold-promotion, lost→fine→block, fine-settlement→unblock) fully enumerated. Both fine-calculation variants (depreciated vs flat replacement; final vs estimate) and pinned round-each-component-then-sum order rendered in precise prose. All enum/state values appear as exact UPPERCASE strings.
- **Contract 3 (§3 Path Purity):** 479 §3 backtick tokens scanned; 0 endpoint paths/methods leaked.

Confirmed: design files SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate Unit Tests — 2026-06-08T12:20:53.000Z

Generated complete test infrastructure for task_0251 strictly from the two design indices (every test traces to exactly one non-stub instance).

**test_helpers/ (9 files):** `__init__.py`, `types.py` (12 entity TypedDicts + 13 status/role enums), `api_client.py` (one method per §4 endpoint incl. `_clock/set`), `api_errors.py` (20-entry ApiErrorId enum + HTTP status map), `assertions.py` (per-entity + `assert_pool_token_invariant`), `factories.py`, `constants.py`, `test_users.py` (opaque Librarian/BranchManager + entity-backed `make_patron_headers(id)`), `fixtures.py`.

**test_suite/ (7 test files + conftest.py):** 73 test functions (74 collected items).

**Coverage:**
- Queue A (Difficulty §1.8): **18/18 instances translated, 0 skipped.** Every instance carries ≥2 distinct tagged test functions (`test_07_*` supplies companion tests).
- Queue B (Corner §1.9): **33/33 non-stub instances translated, 0 skipped.** The 3 `excluded_because` stubs correctly NOT translated; all 3 difficulty cross-references resolve.
- No instances skipped — all design-index claims have verbatim PRD coverage + unique derivability.

**Audits passed:** all 95 PRD citations are contiguous verbatim substrings of PRD.md; every test has exactly one `Design:` tag as last docstring line; all tags resolve to real non-stub instances; no skip/skipif/xfail; no scaffold leakage; all files byte-compile and pytest collects cleanly.

## Step 6: Generate Implementation — 2026-06-08T12:20:53.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`. All five smoke-test suites passed (76 assertions across core CRUD, cascades, calculations, OCC, queue logic, RBAC, validation ordering).

**Files:** Launcher/deps (`start.sh`, `requirements.txt` flask==3.0.3); Entry/infra (`app.py` app factory, `db.py` in-memory store, `errors.py`, `response.py`, `middleware.py` auth/RBAC, `clock.py` logical clock, `timeutil.py`, `constants.py` MAX_RENEWALS=2/PICKUP_WINDOW_DAYS); `routes/` (12 blueprints + `helpers.py`); `services/` (`serialize.py`, `derive.py`, `calc.py` Decimal/ROUND_HALF_UP, `cascade.py` hold-promotion loop, `loans.py`, `reservation.py`).

**Stack/entrypoint:** Python 3 + Flask; `app.py` (`app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=True)`), launched by `start.sh`.

**Storage:** In-memory plain dicts keyed by UUID. Module-level insertion counter for created_at-ascending ordering. Each create stamps id/created_at/updated_at/version=1; mutations bump version + updated_at; derived counters reconcile on mutation and read.

**start.sh contract confirmed:** reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`; pip install guarded; NO data seeded at startup (fresh boot returns empty branches list).

**Note:** `PICKUP_WINDOW_DAYS` unspecified by PRD/scaffold — used conventional 3-day window (documented in `constants.py`); time-based tests drive the logical clock explicitly past `pickup_deadline`.

## Step 7: Run Tests and Iterate — 2026-06-08T12:28:34.000Z

Clean exit — the 8-round parallel sweep is fully green.

## Summary

**Iterations run:** 2 fix-and-sweep iterations (3 total sweeps: initial diagnostic, post-fix, confirmation).

**Tests deleted:** None. One assertion within a test was removed via STEP 1c partial-coverage split (not a full test deletion).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful.

**Assertion correction (test_suite/):**
- `test_suite/test_07_difficulty_second_coverage.py` → `test_declare_lost_reduces_title_total_copy_count`: removed the assertion `after["total_copy_count"] == 0`. **Pattern: derived-field / contradictory-source non-derivability (STEP 1b).** The PRD contains two contradictory sentences about a LOST copy's effect on `total_copy_count`:
  - §2.6 (authoritative definition): "`total_copy_count` is the number of that title's copies that are **not `WITHDRAWN`**", and `LOST`/`WITHDRAWN` are distinct copy statuses. By this definition a LOST copy is non-withdrawn, so it **remains counted** → stays 1.
  - §3.5 (justification clause): "a lost copy leaves ... the non-withdrawn total" → implies 0.

  A faithful PRD-only implementer computing the counter from the explicit §2.6 formula (the proper authoritative source for a derived counter) produces `total_copy_count == 1` — exactly what the reference implementation does (`services/derive.py:76`: `sum(1 for c in title_copies if c["status"] != "WITHDRAWN")`). The two-reader experiment yields divergent implementations, so the `== 0` assertion is not uniquely derivable. Per STEP 1c, I kept the two independently-sound assertions (`before total_copy_count == 1`, and `after available_copy_count == 0`, both directly derivable from §2.6) and removed only the non-derivable one. Scaffold rule that drove the test's generation: `Difficulty/transitive_cascade/declare_lost_cascade_to_patron_block_depth4`.

**Flakiness note:** In the intermediate sweep, `test_create_branch_applies_policy_defaults` reported `error: API server ... could not be restarted` in all 8 rounds (a ~15s boot-readiness timeout, not an assertion failure). This was transient per-test-server boot-latency contention under 8× concurrent CPU load — it did not recur in the confirmation sweep and migrated off the test, confirming it as infra flakiness rather than a logic defect. Server cold-import measured at 0.13s and flask is pre-installed (so `start.sh` skips pip), so no structural boot fix was warranted.

**Final state:** All 8 parallel rounds pass 74/74 with zero failures.

**Orchestrator confirmation sweep (2026-06-08T12:28:34Z):** independently re-ran the 8-round parallel sweep; all 8 results files report passed=74 failed=0 total=74. Artifacts left at `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-06-08T12:32:00.000Z

Done. PRD_FINALIZED.md is produced with a single, minimal, scoped edit.

## Summary

**Line counts:** PRD.md = 288 lines, PRD_FINALIZED.md = 288 lines. One line revised in place; 0% line-count delta.

**Changes (one bullet):**
- §3.5 (Lost Items and Replacement Billing) — *revise* — Replaced the false justification clause "a lost copy leaves both the available pool and the non-withdrawn total" with prose pinning the impl's actual behavior: a LOST copy leaves the available pool (`available_copy_count` drops by one) but, because LOST is distinct from WITHDRAWN, the lost copy stays non-withdrawn and remains counted in `total_copy_count` (so a single declare-lost does not change `total_copy_count`). — `services/derive.py:76`, driven from `routes/loans.py:253-273`.

**Why this is the only edit:** The Step 7 diff applied no fixes to `implementation/` or `test_helpers/`, and deleted no tests. Its sole substantive item was removing the non-derivable assertion `after["total_copy_count"] == 0`, traced to a PRD self-contradiction: §2.6 (authoritative) defines `total_copy_count` as non-withdrawn copies → LOST stays counted (=1); §3.5's narrative clause implied it drops to 0. The implementation follows §2.6 (`derive.py:76`), so §3.5 was the PRD-mismatch site to pin. No other Step 7 item exists, so nothing else was touched.

**Per-edit pre-edit search log (§3.5 edit):**
- (a) Subject: the title-counter cascade on declare-lost — how `total_copy_count` and `available_copy_count` respond to a copy entering `LOST`.
- (b) Paths enumerated/read: `services/derive.py:75-76` (sole counter definitions); `routes/loans.py:230-274` (declare-lost, the only path driving a copy to LOST → calls `reconcile_title`); `grep LOST` across routes/+services/ (confirmed declare-lost is the ONLY LOST-setting path); `serialize.py:64`/`titles.py:35` (pass-through only); §2.6 (authoritative def, already matches impl, left verbatim).
- (c) Wording adjustment: scoped the no-change claim to "declaring a single loaned copy lost does not change that title's `total_copy_count`" rather than a universal invariant, keeping it consistent with the separate title-withdraw path where copies DO become WITHDRAWN and `total_copy_count` legitimately drops.

Note: test_suite/ and test_helpers/ live at the task-dir root (not under workspace/), so the subagent cross-referenced tests via the Step 7 diff + results.*.json records; alignment performed against implementation/ as required.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-08T17:54:08.536Z

Resumed as a standalone Step 9 (prior run had left PRD_COMPLETED.md as a byte-identical cp of PRD_FINALIZED.md — the completeness scan had not actually executed). Re-ran the full PRD-vs-implementation/ scan; PRD_COMPLETED.md now diverges from PRD_FINALIZED.md (md5 3d68ac… → b01c82…, +572 chars, 288→288 lines, no new sections). Orchestrator spot-checked the three highest-risk error-code claims against impl: holds.py:151 (premature expire → ERR_NOT_YET_DUE), reservations.py:164-165 (check-in before start_at → ERR_NOT_YET_DUE), ill_requests.py:114-115 (approve non-CLEAR patron → ERR_PATRON_BLOCKED) — all confirmed faithful.

Subagent summary (verbatim):

**File metrics**
- Source: `PRD_FINALIZED.md` (288 lines, 48,451 chars)
- Output: `PRD_COMPLETED.md` (288 lines, 49,023 chars)
- Char delta: +572 (diff reports +568 net of the cp; 10 in-paragraph edits, no new lines, no new sections)

**Counts**
- Ambiguity-pins: 9
- Mismatch-revisions: 1

**Changes**
- §2.4 — insert — ambiguity — pinned `version` initial value to `1` on creation (PRD said only "begins at its initial value") — `db.py:59` (`stamp_create` sets `version = 1`).
- §2.11 — insert — ambiguity — pinned the `_clock/set` response: 200 OK with a `data` object carrying a single `now` ISO-8601 field (PRD was silent on shape) — `routes/clock_routes.py:26`.
- §3.1 — insert — ambiguity — pinned the set-card-status request field name to a required `card_status` body field (PRD named no field) — `routes/patrons.py:78`.
- §3.3 — insert — ambiguity — pinned that an omitted `projected_return` defaults to the current server clock for the fine estimate (PRD only described the supplied case) — `routes/loans.py:107-114`.
- §3.6 — insert — ambiguity — pinned the hold pickup window to three whole days (`pickup_deadline = ready_at + 3d`; PRD left the width unspecified) — `constants.py:16` (`PICKUP_WINDOW_DAYS = 3`), `services/serialize.py:105`.
- §3.6 — revise — mismatch — narrowed the premature expire-ready error from the two-option "`ERR_PICKUP_EXPIRED`/`ERR_NOT_YET_DUE`-class" to the single code `ERR_NOT_YET_DUE` impl returns — `routes/holds.py:151`.
- §3.7 — insert — ambiguity — pinned that a reservation check-in attempted before `start_at` is rejected with `ERR_NOT_YET_DUE` (PRD stated the timing rule but not the code) — `routes/reservations.py:164-165`.
- §3.7 — insert — ambiguity — pinned the room `reservation_buffer_minutes` to the booking patron's home branch (resolved via the patron's `branch_id`), disambiguating which "branch" supplies the buffer — `routes/reservations.py:71-72` (`_branch_for_patron`).
- §3.7 — insert — ambiguity — pinned the set-service-status request field name to a required `status` body field (PRD named no field) — `routes/resources.py:75`.
- §3.8 — insert — ambiguity — pinned that ILL `approve` on a non-`CLEAR` patron is rejected with `ERR_PATRON_BLOCKED` (PRD stated the CLEAR precondition but not the code) — `routes/ill_requests.py:114-115`.

**Notes on items deliberately left unchanged (already pinned or impl matches PRD):** patron-record/account-summary reads are intentionally not ownership-gated (PRD §2.1 scopes patron ownership to Loan/Hold/Reservation/EbookLoan only — impl matches); ILL creation requires an ACTIVE card but does not block on fines (matches PRD §2.8 BLOCKED list); fine-free branches still report `overdue_days`/`chargeable_days` in estimates with `estimate_cents=0` (matches §3.3); lost-item `total_copy_count` retention is already explicitly pinned in §3.5. Low-value validation rejections (`condition_factor` out of 0.0–1.0, `capacity >= 1`, `total_licenses >= 0` → `ERR_INVALID_REQUEST`) were left alone to keep the patch minimal — they are only weakly observable and the valid domains are already stated in PRD prose.

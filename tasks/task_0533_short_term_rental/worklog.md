# Worklog — task_0533_short_term_rental

## Step 1: Create Task Directory — 2026-07-01T00:00:00.000Z

Created `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0533_short_term_rental/` with `workspace/` subdirectory (pre-allocated task dir, used directly per instructions).

## Step 2: Generate Scaffold — 2026-07-01T00:00:00.000Z

Clean. All three files are generated, parse correctly, and pass the scaffold linter.

## Summary

Generated three scaffold artifacts for **task_0533_short_term_rental** at **Expert** difficulty. All pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Files (all under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0533_short_term_rental/`):**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** primary archetype `compliance_audit` + secondary `quota_allocation`; layers = rate_threshold_triggers, dual_variant_calculation, cascading_side_effects, optimistic_concurrency; **flat topology** (empty `api_prefix`, all collections top-level siblings), **branching** state-machine shape, `peer_roles` model, immediate consistency.

**Entities (9):** Zone, Host, Property, Permit, LotteryRound, Complaint, TaxFiling, ListingReport (append-only, `common_fields:false`), Platform.

**State machines (4):**
- Permit — branching + cyclic self-loop: DRAFT→{ISSUED | LOTTERY_PENDING | REJECTED}; ISSUED→ACTIVE; ACTIVE↔SUSPENDED; ACTIVE/SUSPENDED→REVOKED; ISSUED/ACTIVE→EXPIRED (auto); ACTIVE→ACTIVE (renew).
- Complaint — OPEN→{DISMISSED | UPHELD} with a depth-3 cascade on uphold.
- TaxFiling — DRAFT→FILED→{REMITTED | DELINQUENT} with FILED→DRAFT amend loop.
- LotteryRound — OPEN→DRAWN (waterfall seat award by `created_at`).
- Plus 2 `concurrency_rules` (OCC): `renew-stale-permit`, `draw-stale-lottery-round`.

**Calculations (5):** `occupancy_max` (2·bedrooms+1); `tot_due` (two-tier TOT, round-per-share-then-sum); `tax_penalty` (flat + daily interest, min-capped); `host_strike_standing` (dual-variant: host-scoped vs permit-scoped strike aggregation); `platform_match` (projection resolving MATCHED/ADDRESS_MISMATCH/NO_PERMIT/PERMIT_INACTIVE).

**Endpoints:** 39 (includes filtered-list reverse-reachability GETs for every FK and a `/_clock/set_current_utc` test-driving endpoint, default `2026-05-01T00:00:00Z`).

**Error catalog:** 24 error codes.

**Design instance counts:**
- §1.8: **18 instances** across all 9 Difficulty Rules (exactly 2 each).
- §1.9: **9 sections, 34 active instances + 3 `excluded_because` stubs** (37 total); all stub `difficulty_instance` references resolve to real §1.8 instance names.

All formula-derived assertions were computed in code (e.g., tot_due 43000 for 10 nights/$5000; 61200 for the 20-night straddle; penalty 3575 interest-branch vs 10750 cap-branch; remittance total 46575).

## Step 3: Copy Shared Files — 2026-07-01T00:00:00.000Z

Copied `INSTRUCTION.md` into `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-01T00:00:00.000Z

All states, enums, and OCC fields present. The PRD is complete and passes all three hard contracts.

## Summary

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0533_short_term_rental/workspace/PRD.md` from the scaffold.

**Structure:**
- **Section count:** 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue)
- **Subsections:** 18 (§2 has 9 domain-derived cross-cutting subsections including the fixed §2.2; §3 has 9 workflow subsections organized by lifecycle/entity)
- **Line count:** 241 lines

**Hard contract verification (all PASS):**
- **Contract 1 (Field-Name Coverage):** All 50 required identifiers appear verbatim in backticks. 0 missing.
- **Contract 2 (Rule Coverage):** Both OCC rules fully expressed; depth-3 uphold cascade, dual strike scopes (permit-level 2/4 vs host-level 3), density-cap fork to `LOTTERY_PENDING`, order-pinned two-tier TOT calc, capped penalty calc, platform-match resolution order, and issuance gate ordering all narrated. All 23 error IDs surface in §2/§3 narrative.
- **Contract 3 (§3 Path Purity):** 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos in §3.

§2.2 emitted verbatim; §4 table has exactly 4 columns; §5 table exactly 2 columns.

**Confirmation:** Neither design YAML was read, opened, grepped, or referenced. Only `SCAFFOLD.yaml`, the skill spec, and the fixed §2.2 source file were consulted.

## Step 5: Generate Unit Tests — 2026-07-01T00:00:00.000Z

All infrastructure is generated and validated. 

## Summary

I generated the complete test infrastructure for `task_0533_short_term_rental` from the two design indices (the only permitted test source), applying the PRD-first two-condition filter to every instance.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (8 status enums + 8 entity TypedDicts, with `ListingReport` correctly omitting `updated_at`/`version` per its `common_fields: false`), `api_client.py` (one method per endpoint), `api_errors.py` (23 error IDs + HTTP-status map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (TOT/penalty/standing thresholds), `test_users.py` (opaque + entity-backed role headers with per-instance `make_host_headers`/`make_platform_headers` builders for identity threading), `fixtures.py` (composite setup helpers: issued/active/suspended permits, filed/delinquent filings, renewal-window permits, lottery-pending permits), and the `__init__.py` barrel.

**Stage 2 — `test_suite/`** (conftest + 9 test files, **74 tests total**):
- Queue A (Difficulty): all **18 instances** translated, each with **≥2 tests** (primary facet + a distinct PRD-grounded second facet). All passed the filter — none skipped.
- Queue B (Corner): all **34 non-stub instances** translated with **≥1 test** each. The **3 `excluded_because:` stubs** were correctly not translated (their `difficulty_instance` cross-references all resolve to real, covered §1.8 instances).

**Verification performed:**
- Every test docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line (74 tests = 74 Design lines).
- All emitted tags resolve to real instance `name:`s in the source YAMLs (no phantom names, no dual-tags, no untagged tests).
- Independently recomputed and confirmed all literal expected values: `tot_due` 43000 (base) / 61200 (straddle), penalty 10750 (cap) / 3575 (interest), remit 46575, expires_at 2027-05-01 / 2028-05-01, max_occupancy 5, cascade apc=0/BARRED, lottery apc=2.
- All files compile; no `skip`/`xfail`/`skipif`; no scaffold-table references in emitted code; PRD citations spot-checked as verbatim (modulo backticks/em-dash whitespace).

One design note worth flagging: the difficulty instance `host_strike_standing_risk_scoring_on_host` has narrative `setup:`/`distinguishing_aspect:` text describing "two UPHELD complaints / strike_total=2", but its actual `setup_api_calls` + `assert` block files one NOISE complaint and asserts `strike_total == 1, GOOD`. I translated the authoritative `test_recipe` (asserts), per §2.1 step 6.

## Step 6: Generate Implementation — 2026-07-01T00:00:00.000Z

The implementation is complete and verified.

## Summary

I generated a complete Python + Flask implementation of the Short-Term Rental City Registration & Lodging Tax API at `workspace/implementation/`.

### Files produced
- `start.sh` — foreground launcher with guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry point, error handlers (ApiError + Werkzeug HTTPException routing)
- `db.py` — in-memory store (starts empty every boot, no seeding), UUID/api-key/request-id minting
- `clock.py` — logical clock (default `2026-05-01T00:00:00Z`, never falls back to wall time), ISO-8601-with-3ms formatting
- `response.py` — exact envelope (`meta`/`response_type`/`data`; pagination fields in `meta`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role enforcement
- `validation.py` — body parsing, pagination (limit 10/1–100, offset ≥0)
- `errors.py` — full error catalog
- `services/calc.py` — Decimal/ROUND_HALF_UP calculations (occupancy, two-tier TOT, penalty)
- `services/domain.py` — serialization, lazy auto-transitions, zone density counting, strike cascades
- `routes/api.py` — all 37 endpoints

### Verified behaviors (via live curl tests)
- Response envelope, auth (401/403), pagination, all CRUD; issuance gate ordering; TOT two-tier per-line-then-sum rounding; penalty flat+interest capped at 25%; complaint cascade depth-3; lottery waterfall by created_at ASC; OCC stale-version 412 on renew and draw; lazy transitions (EXPIRED/DELINQUENT); renewal window; primary-residence attestation gate; platform match; TaxOfficer blocked from platform key.

### Key design notes
- Flask 3.0.3 already installed system-wide, guarded install is a no-op — boots fast under per-test-server reboots.
- `due_at` interpreted as last calendar day of period (00:00:00 UTC) + 30 days.
- Body-field parsing precedes FK existence checks on POST creates; 400 for missing/malformed, 404 for present-but-nonexistent FKs.

## Step 7: Test-and-Fix Loop — 2026-07-02T00:00:00.000Z

## Summary

**Iterations run:** 2 sweeps (initial 64/74 → 73/74 after fixes → 73/73 clean). Orchestrator re-ran a confirming 8-round parallel sweep: all 8 rounds 73/73.

**Root cause map:** The initial run showed 64/74 stable across all 8 rounds (10 real failures, no flakiness). All were traceable to test-artifact defects, not implementation bugs.

### Tests deleted (1)
- **`test_draw_stale_lottery_round_version_rejected`** (`test_suite/test_04_issuance_and_lottery.py`) — DELETED per STEP 1b UNIQUE-DERIVABILITY (error-precedence / unreachable-state collapse). The lottery draw is terminal (`OPEN → DRAWN`) and the PRD defines no operation that advances an OPEN round's `version`. Per PRD §2.9 the state check precedes the version guard, so any second draw always lands on `ERR_INVALID_STATE`, never the asserted `ERR_STALE_VERSION`. A faithful implementer cannot make this test pass; the outcome is not uniquely determined by the cited §2.7 sentence. (Contrast: the permit-renewal stale-version test is reachable via a suspend+reinstate version bump that leaves the window open, so it was fixed rather than deleted.)

### Fixes applied to `test_helpers/` (1 file)
- **`fixtures.py`** — `setup_filed_filing`: defaulted the filing period to **May 2026** so `due_at` (2026-06-30) lands after the startup clock (2026-05-01). Previously it used March 2026, making `due_at` = 2026-04-30, which is *before* the startup clock — so the filing tripped the §2.5 lazy `DELINQUENT` auto-transition on its very next touch and never stayed FILED. This one fixture bug caused 5 failures (all amend tests + partial-remittance). `setup_delinquent_filing` was pinned to March 2026 explicitly to preserve its intended past-due `days_late` arithmetic.

### Fixes applied to `test_suite/` (2 files, 3 assertions)
- **`test_02_permit_lifecycle.py`** — `test_renew_extends_expiry_by_365_from_anchor`: corrected expected `expires_at` from `2028-05-01` to `2028-04-30`. PRD says "365 days from the anchor"; 2027-05-01 + 365 days crosses leap-year Feb 2028 (366-day span), landing on 2028-04-30. The implementation's `timedelta(days=365)` is PRD-faithful; the assertion was wrong.
- **`test_02_permit_lifecycle.py`** — `test_renew_stale_version_rejected`: rewrote the unreachable double-renew setup (a successful renew moves the window 365 days out, so a second renew fails the window check first). Replaced with a suspend (upheld OVER_OCCUPANCY, host stays GOOD at 2 pts) + reinstate cycle that bumps the permit version while leaving `expires_at`/window intact, so a renew with the pre-cascade version now legitimately trips `ERR_STALE_VERSION`.
- **`test_04_issuance_and_lottery.py`** — `test_barred_host_cannot_be_issued` and (formerly) the lottery test: passed `expected_status=201` to `validate_success` on `create_complaint`/`create_lottery_round` calls. Per PRD §4 creates return 201; the tests were asserting the default 200.

### Fixes applied to `implementation/`
None. The implementation was PRD-faithful for all 10 failures; every fix was in the test artifacts.

## Step 8: Finalize PRD — 2026-07-02T00:00:00.000Z

## Summary

**Line counts:** PRD.md = 241 lines, PRD_FINALIZED.md = 241 lines. Line-count delta: 0 (+0.0%). The single edit appended prose to an existing line (§2.7) without adding lines.

**Changes (1):**
- §2.7 — insert — Appended a clause pinning that on both OCC-guarded operations (renew, draw) the version guard is evaluated as a business rule *after* the state check, so a second draw on an already-`DRAWN` round yields `ERR_INVALID_STATE`, never `ERR_STALE_VERSION` — traces to `routes/api.py:705-715` (draw: state check precedes version check) and `routes/api.py:373-399` (renew: state check precedes version check).

**Why only one edit** (the other 4 step_7_diff items require none):
- Deleted draw stale-version test → genuine PRD-silence: §2.7 alone did not order the version guard relative to the state check. This is the one edit.
- Renew 365-days-from-anchor / 2028-04-30 → PRD §3.6 already says "365 days from the existing anchor"; impl uses `timedelta(days=365)`. Fully determined; the assertion was arithmetically wrong. No PRD gap.
- Renew stale-version reachability via suspend+reinstate → pure test-setup rewrite over already-PRD-determined enforcement-ladder behavior. No silence.
- Creates return 201 → PRD §4 already states "Creating a new resource returns HTTP 201". No gap.
- fixtures.py May-2026 default → pure test-fixture bug, no PRD relation.

## Step 9: Complete PRD — 2026-07-02T00:00:00.000Z

## Summary

Produced `workspace/PRD_COMPLETED.md` by copying `PRD_FINALIZED.md` and applying 8 minimal inline edits to pin implementation behavior.

- **Line counts:** PRD_FINALIZED.md 241 → PRD_COMPLETED.md 241 (all in-paragraph). **Char delta:** +861 (38766 → 39627).
- **Counts:** ambiguity-pins = 5, mismatch-revisions = 3.

Changes:
- §2.1 (RBAC) — insert — ambiguity — platform `api_key` OR persisted `id` both accepted as matching `X-User-ID` — routes/api.py:783.
- §3.1 (Zones) — revise — mismatch — `active_permit_count` recomputed over ISSUED/ACTIVE/SUSPENDED (not just ACTIVE/SUSPENDED) — services/domain.py:77.
- §3.2 (Primary residence) — insert — ambiguity — re-attesting same property is idempotent, host `version` unchanged — routes/api.py:166-169.
- §3.8 (file gates) — revise — mismatch — `ERR_NO_NIGHTS_TO_FILE` checked before `ERR_PERMIT_NOT_FILEABLE` — routes/api.py:604-607.
- §3.8 (due_at) — revise — ambiguity — due_at = period last calendar day at 00:00:00Z + 30 days — routes/api.py:518-529.
- §3.8 (remit) — insert — ambiguity — `payment_cents` must be ≥ 0 — routes/api.py:637.
- §3.6 (reinstate) — insert — ambiguity — reinstating at 4 cumulative strikes rejected with ERR_INVALID_STATE (409) — routes/api.py:411-412.
- §3.9 (Platforms) — insert — ambiguity — duplicate `platform_name` rejected with ERR_INVALID_REQUEST (400) — routes/api.py:748-749.

## Pipeline Complete — 2026-07-02T00:00:00.000Z

All 9 steps done. Final 8-round parallel sweep: 73/73 passing across all rounds. Deliverables: SCAFFOLD.yaml (+DIFFICULTY/CORNER designs), workspace/INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (73 tests), workspace/implementation/ (Python+Flask, start.sh).

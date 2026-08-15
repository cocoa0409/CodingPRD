# Worklog — task_1813_content_licensing_distribution_windowing

## Step 1: Create task directory — 2026-08-14T18:12:00.000Z

Pre-created by pipeline launcher: `tasks/task_1813_content_licensing_distribution_windowing/` + `workspace/` (skipped per orchestrator instructions).

## Step 2: Generate scaffold — 2026-08-14T19:02:00.000Z

All three scaffold artifacts are generated and verified.

### Files written

- `SCAFFOLD.yaml` — §1.0–§1.7 (scenario verbatim, fixed response envelope, 10 entities, 7 state machines, 2 OCC concurrency rules, 7 calculations, ~40 ordered validations, 43 endpoints, 44 errors, 4 roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 19 instances (every §0.5 rule ≥2; combinatorial_formula has 3, one per mode a/b/c)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 56 active instances + 6 `excluded_because:` stubs across all nine claim-extraction-guide sections

### Design highlights

- **Complexity profile**: primary archetype `temporal_windowing` + secondary `ledger_reconciliation`; flat topology (peer entities under `/licensing/*`, FK-linked); cyclic state-machine shape; segregation-of-duties role model (statement finalizer ≠ payer, enforced by X-User-ID comparison); immediate consistency; layers: optimistic_concurrency, cascading_side_effects, scheduled_actions, derived_field_reconciliation.
- **Entities**: Title (with territory embargo list), RightsHolder, Platform (with delivery spec), RightsSlot (territory/language/window inventory), AvailPackage (embedded offer lines with full deal terms), LicenseAgreement, DeliveryBatch, TakedownNotice (system-scheduled at license_end), RevenueReport, RoyaltyStatement.
- **Key difficulty mechanics**: half-open same-cell exclusivity overlap vs closed buffered cross-window holdback (Rule 8, opposite adjacency behavior); MG recoupment waterfall with exact-equality boundary; termination credit DAILY vs MONTHLY proration divergence (400000 vs 300000 on identical inputs); statement attribution BY_REPORT_DATE vs BY_USAGE_PERIOD (2000 vs 1500 on identical reports); gross-keyed volume-discount tier with pinned evaluation order and pro-rata remainder allocation; depth-3 cascade (slot withdraw → line BLOCKED → all-blocked package EXPIRED → lines NOT_SELECTED) and depth-2 cascade (license terminate → slot freed → line unblocked); two OCC rules on LicenseAgreement.version (report submit, extend); logical clock with mandatory default `2026-08-01T00:00:00Z` and synchronous expiration sweep.
- All fixture arithmetic was pre-computed and written as literals in `assert:` lines (recoupment splits, discount tiers/allocations, proration credits, statement totals).

### Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (43 endpoints, 10 entities, 19 §1.8 + 56 §1.9 active instances, 509 calls scanned)
- Separate audit script confirmed: every `grounds:` reference resolves to a declared §1.1–§1.7 element, instance names unique across both design files, all 9 difficulty rules meet their ≥2-instance minimum, excluded stubs reference real §1.8 instances and carry no `test_recipe`.
- Forbidden concurrency vocabulary scan is clean (one "in parallel" instance found and reworded).
- File split honored: neither design key appears in SCAFFOLD.yaml; each design file has exactly its single top-level key.
- All 44 error codes are exercised by at least one instance across §1.8/§1.9.

## Step 3: Copy shared files — 2026-08-14T19:04:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1813_content_licensing_distribution_windowing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T19:08:00.000Z

All three hard contracts PASS. The PRD is complete and written to `workspace/PRD.md` (317 lines).

### Summary of generation

- **Structure**: §1 Introduction (3 paragraphs, business-context angle); §2 with 10 domain-derived subsections (RBAC, response envelope verbatim, pagination, common properties, logical clock + expiration sweep, monetary precision, OCC, dual interval semantics, validation ordering, embedded package lines); §3 with 10 subsections organized by lifecycle/business process (catalog → inventory → packaging → encumbrance cascade → acceptance → license lifecycle → delivery → revenue reports/recoupment → statements → takedown notices); §4 endpoint table (4 columns, 44 endpoints); §5 error catalogue (2 columns, 44 errors).

- **Key domain decisions**: §2.8 was dedicated to the critical half-open vs closed-and-buffered interval distinction (the system's primary archetype); §2.5 covers the logical clock with pinned sweep order (slots → licenses → packages) and the startup default `2026-08-01T00:00:00Z`; §3.4 isolates the 3-hop encumbrance/block cascade; §3.5 walks the volume-discount formula step-by-step in pinned order (tier keyed on gross, not net); §3.6 covers the two proration variants (`DAILY_PRORATION` vs `MONTHLY_PRORATION` with 30-day blocks); §3.9 spells out both attribution variants and the segregation-of-duties rule.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 84 required (incl. endpoint inputs, clock outputs, line sub-fields), 84 present, 0 missing
- endpoints[].request_body: covered in the 84 above
- endpoints[].query_params: covered (filters named inline; limit/offset in §2.3)
Status: PASS

Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed (validation priority order §2.9; per-rule triggers in §2/§3 near the workflow guarded)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoints, expected_license_version, ERR_STALE_VERSION/412 all named in §2.7 + restated in §3.6, §3.8)
- state_machines[].transitions: 19 checked, 19 fully expressed (preconditions + error ids + side effects)
- calculations[]: 6 checked, 6 fully expressed (recoupment_split, package_volume_discount, statement_attribution + 2 variants, termination_credit + 2 variants, holdback_derivation + matrix, slot_conflict_check, expiration_sweep)
- validations[] conditions: 33 matchable to error_id in prose
- endpoints[].side_effects / applies_to: expressed in workflow narratives
- entities[].fields[] structured content: defaults, enums, computed/source semantics reconstructible
- sibling-branch symmetry: fee-model branches, attribution variants, proration variants, and cascade hops rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 460
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 matches the canonical verbatim block byte-for-byte (verified by string equality against `section-2.2-response-structure.md`).

## Step 5: Generate unit tests — 2026-08-14T19:40:00.000Z

Generated complete test infrastructure and suite for task_1813.

### Deliverables

**`test_helpers/`** (9 files):
- `types.py` — 10 entity TypedDicts (all `common_fields: true`) + 15 status/field enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (41 methods, `/licensing` prefix)
- `api_errors.py` — all 43 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_same_instant` (parse-compare datetimes) + `assert_recoupment_ledger_invariant`
- `factories.py`, `constants.py` (discount tiers, HOLDBACK_MATRIX, default clock), `test_users.py` (opaque role constants + `make_platform_buyer_headers(platform_id)` for the entity-backed role), `fixtures.py` (catalog workspace with identity-threaded buyer headers, slot/package/license builders, OCC-threaded `book_report`, delivered-batch helper, statement lifecycle helpers)

**`test_suite/`** — `conftest.py` + 9 test files, **89 tests**, organized test_01 catalog/envelope → test_09 royalty statements.

### Verification results
- All modules compile and import cleanly; pyflakes clean on `test_suite`
- Every test has exactly one `Design:` tag resolving to a real instance; stub tags unused (6 stubs correctly untranslated, all `difficulty_instance` pointers resolve)
- All 136 PRD citations verified verbatim against PRD.md (whitespace-normalized grep)
- Difficulty coverage 17/19 instances at ≥2 tests; corner coverage 55/56 non-stub at ≥1 test

### Three instances skipped per the PRD-first two-condition filter
1. **`Difficulty/transitive_cascade/license_terminate_frees_slot_unblocks_line_chain`** — PRD-contradicted: the instance's package has a single line on the slot, so when the exclusive license blocks that line, PRD §3.4 hop-2 ("an OFFERED package whose every line is now BLOCKED … the package itself moves to EXPIRED") expires the package and hop-3 flips the line to NOT_SELECTED. The asserted `mid_line == BLOCKED`, "package OFFERED throughout", and BLOCKED→OFFERED restoration are unreachable under PRD rules.
2. **`Difficulty/cross_entity_state_dependency/package_accept_requires_slot_available`** — same hop-2 contradiction: the single-line package auto-expires when its line is blocked, so the accept deterministically yields `ERR_PACKAGE_NOT_OFFERED` (state check, priority 4) rather than the asserted `ERR_LINE_BLOCKED` (priority 8), and "package remains OFFERED" is false.
3. **`Corner/endpoints/license_list_filtered_by_slot`** — PRD names list filters for titles, platforms, slots, batches, reports, statements, and notices, but never any filter (including `slot_id`) on `GET /licensing/license-agreements`; fails the coverage condition.

Two PRD-derivability adjustments applied throughout: timestamp equality is asserted as instant equality (PRD §2.4's "three fractional digits" leaves rendering open), and version assertions are relative (`v+1`) since PRD never pins the initial version value. The `license_list_filtered_by_slot`-style assertion inside `accept_creates_licenses_and_notices_atomically` was routed through PRD-covered reads instead (per-license GETs + notice `license_id` filter).

## Step 6: Generate implementation — 2026-08-14T19:40:00.000Z

The implementation is complete and verified. (Ran concurrently with Step 5 in a single message.)

### What was delivered

A complete Python + Flask implementation at `workspace/implementation/`:

- `start.sh` — executable launcher, `cd "$(dirname "$0")"`, guarded dependency install (`pip install` only if `import flask` fails, per the per-test-server reboot contract), `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000). Verified: fresh boot in ~0.57s with empty store, 3 consecutive reboots each clean.
- `app.py` — Flask factory, blueprint registration, ApiError/404/405/catch-all handlers.
- `util.py` — UUIDs, `req_…` request ids, wall-clock envelope timestamps (3 fractional digits), the **logical clock** (starts exactly `2026-08-01T00:00:00Z`, never wall-clock), second-precision `…Z` datetime format for all entity/logical timestamps (matches the design docs' literal assertions like `created_at == 2026-08-01T00:00:00Z`), exact `round_half_up` integer arithmetic + Decimal-based percentage rounding.
- `store.py` — in-memory store, **no seeding**; `insert` mints id/created_at/updated_at (from the logical clock)/version=1 plus an internal insertion sequence for `created_at ASC` tie-breaks; `mutate` = version+1 + updated_at (also applied to cascade-touched entities).
- `errors.py` / `response.py` / `auth.py` / `validate.py` — full error catalog with exact ids/statuses; the fixed envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list meta gains `limit/offset/total_count/has_more`, defaults 10/0 clamped to 1..100); `X-User-ID`/`X-User-Role` auth (401/403) with PlatformBuyer entity-backed ownership; schema validators (all end>start rules → 400).
- `domain.py` — holdback matrix, half-open same-cell exclusivity vs closed buffered cross-window holdback checks (exclusivity reported first), encumber/block/release cascades, volume discount (gross-keyed tiers, per-line round-half-up allocation, remainder to lowest-index gv>0 line), termination credits (DAILY seconds-ratio, MONTHLY 30-day blocks floor/ceil), recoupment waterfall + chronological replay on reversal, statement attribution (BY_REPORT_DATE closed interval / BY_USAGE_PERIOD intersection; per-report rounded sums; holder rounding once), and the pinned-order expiration sweep (slots → licenses → packages, created_at ASC) with the five tallies.
- `routes/` — all 33 endpoints with the role matrix, buyer list scoping (platform_id filter must equal caller, defaults to own; foreign single-GETs → 403), and the validation priority pipeline: auth → role → path existence → ownership → body schema → body-id existence (declaration order) → state (incl. license-state before OCC 412) → safety → referential → temporal → constraint → fiscal.

### Key fidelity decisions (from cross-reading PRD vs design docs)

- **Cascade asymmetry**: slot withdraw/expiry runs all three hops (block → all-blocked package EXPIRED → NOT_SELECTED), but encumbrance by an exclusive license only blocks lines without expiring packages — the difficulty design's `license_terminate_frees_slot_unblocks_line_chain` pins `mid_line == BLOCKED`, `package OFFERED throughout`, while the withdraw test pins full depth-3 expiry. This was the one real trap; caught and fixed via smoke testing.
- Validation order follows the scaffold priority table / PRD §2.9 category order (verified against both priority-pair difficulty tests: state beats fiscal, temporal beats constraint).
- No error id exists for duplicate `title_code` or double report reversal — left title_code unenforced; double-reversal returns 400 ERR_INVALID_REQUEST.

### Verification

Two smoke suites (≈90 assertions) replaying the design docs' pinned scenarios all pass: discount tier boundary at exactly 2,000,000 (10%, allocations 1,350,000/450,000), evaluation-order case (gross 2,100,000 → 10%), remainder allocation, DAILY 400,000 vs MONTHLY 300,000 credits, three-report waterfall with exact-exhaustion, reversal replay invariant, per-report rounding (1+1=2 not 1), statement attribution divergence (4,000/2,000 vs 3,000/1,500 with PAID not blocking), half-open adjacency vs closed holdback boundary (12-31 conflicts, 01-01 succeeds), offer expiry at the exact instant, withdraw/terminate cascade chains, OCC 412s, SoD 403, notice cancel/replace on extend, sweep tallies, pagination, buyer scoping, and all ten entity-specific 404s.

## Step 7: Test-fix iteration loop — 2026-08-14T20:05:00.000Z

**Exit condition met: clean 8-round parallel sweep — 89/89 passed in all 8 rounds.**

### Iterations run
2 sweeps (16 test rounds total).

### Round 1 (diagnosis)
- 6/8 rounds fully clean; rounds 3 and 6 each failed exactly one test: `test_03_rights_slot_lifecycle.py::TestSlotEncumberReleaseCycle::test_slot_cycles_available_encumbered_available_encumbered`.
- Failure detail: `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104))` / `RemoteDisconnected` raised at the test's 5th HTTP call (`POST /licensing/license-agreements` via `fixtures.create_direct_license`). No assertion ever tripped.
- STEP 0 forensic: server logs (`/tmp/prd_bench_server_{46585,45159}.log`, segments at 19:39:36) show both affected server generations alive and answering the 4 setup requests, with the failing request **never arriving** and no Python traceback — ruling out an implementation crash.
- STEP 1: the test's assertions trace verbatim to PRD §3.4 ("the slot moves from `AVAILABLE` to `ENCUMBERED`") and §3.6 ("the slot moves from `ENCUMBERED` back to `AVAILABLE`… the line-unblock cascade restores `BLOCKED` lines") — covered and uniquely derivable; test stays.
- STEP 2: root cause is in the test artifact, not the implementation. The runner restarts the server via SIGKILL before every test; `test_helpers/api_client.py`'s session pooled keep-alive connections, so a stale connection to the just-killed server generation could race the incoming RST mid-write (lockstep timing across the 8 parallel rounds made this test the usual victim). **Fixture-level transport bug.**

### Tests deleted
None.

### Fixes applied to `test_helpers/`
- `test_helpers/api_client.py` — added `ApiClient.__init__` that sets `self.session.headers["Connection"] = "close"`. Every request now uses a fresh TCP connection, so a SIGKILLed previous server generation can never poison a pooled connection. Transport-only change; no assertion touched. Verified header propagation via `requests.Session.prepare_request`.

### Fixes applied to `test_suite/`
None.

### Fixes applied to `implementation/`
None — the implementation was behaviorally correct on every round (all failures were transport-level, pre-assertion).

### Round 2 (verification)
All 8 concurrent rounds: 89 passed / 0 failed / 89 total. No flakiness observed.

## Step 8: Finalize PRD — 2026-08-14T19:50:00.000Z

Verification complete. Conclusion: **no PRD edit is warranted — PRD_FINALIZED.md is a byte-identical copy of PRD.md.**

**Analysis of the single Step 7 item against HARD SCOPE:**

The only fix was `test_helpers/api_client.py` adding `Connection: close` to the test client's session — explicitly transport-only, with zero `implementation/` fixes, zero `test_suite/` fixes, and zero test deletions.

- (a) Subject of the only candidate edit: HTTP client connection reuse vs. server restarts. This is **not implementation behavior** — the PRD specifies the licensing/windowing API's behavioral contract (state machines, cascades, calculations, errors); the test harness's TCP pooling strategy is a fixture concern the PRD neither could nor should pin.
- (b) Impl paths enumerated and checked: `implementation/domain.py` (slot lifecycle: `encumber_slot` at lines 439-443, release at 454-457, sweep at 742-751, cascade call at 550), `implementation/routes/licenses.py`, `implementation/app.py`. The behavior exercised by the flaky test (AVAILABLE→ENCUMBERED→AVAILABLE→ENCUMBERED with line unblock) is already uniquely pinned verbatim by PRD §3.4 (line 144: "the slot moves from `AVAILABLE` to `ENCUMBERED`. The transition is idempotent...") and §3.6 (line 148: "the slot returns from `ENCUMBERED` to `AVAILABLE`. Then the unblock hop: lines... return to `OFFERED`"), and the implementation matches it exactly. The Step 7 failure (`ConnectionResetError` on the 5th HTTP call, pre-assertion, no server traceback) was a keep-alive race with the runner's SIGKILL restart — a pure fixture bug.
- (c) Wording adjustment: none — no edit committed, since the fix reveals neither PRD silence about implementation behavior nor any PRD/impl mismatch.

**Summary on exit:**

- **Line counts / %-delta:** PRD.md = 317 lines; PRD_FINALIZED.md = 317 lines; **0% delta** (confirmed byte-identical via `cmp`).
- **Changes:** none.
- **Pre-edit search log:** zero edits committed; the single candidate (transport behavior) was analyzed and rejected as out of HARD SCOPE per (a)/(b)/(c) above.

**File produced:** `workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md). This is the legitimate outcome under the HARD SCOPE rule: the Step 7 diff contains only a fixture-level transport fix and explicitly records that "the implementation was behaviorally correct on every round," so there is no PRD silence or mismatch to patch.

## Step 9: Complete PRD — 2026-08-14T19:58:00.000Z

PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md 317 lines / 45,547 chars → PRD_COMPLETED.md 320 lines / 48,070 chars (delta: +3 lines, +2,523 chars; 33 changed diff lines).

**Counts:** 12 ambiguity-pins, 6 mismatch-revisions (18 total changes; no new sections added, all inline inserts/revisions).

**Changes:**

- §2.1 — insert — ambiguity — pinned that only the avail-package and license-agreement lists accept a `platform_id` filter; revenue-report, delivery-batch, and takedown-notice lists are always auto-scoped to the caller's platform via the license chain — implementation/routes/reports.py:43-44, batches.py:61-62, notices.py:22-23
- §2.2 — insert — ambiguity — pinned `ERR_NOT_FOUND` (404) for unmatched routes and unsupported methods (plus one canonical row added to the §5 error table) — implementation/app.py:43-49
- §2.3 — insert — ambiguity — pinned non-integer `limit`/`offset` falling back to defaults, out-of-range clamping, `created_at` ties broken by insertion order, and the `has_more` formula (`offset` + returned items < `total_count`) — implementation/domain.py:221-239, store.py:36-40, response.py:21
- §2.4 — revise — mismatch — `created_at`/`updated_at` are logical-clock values serialized at whole-second precision (`...Z`); the 3-fractional-digit format applies only to the envelope's wall-clock `api_request_timestamp` — implementation/util.py:51-55, store.py:27-28, util.py:24-27
- §2.4 — insert — ambiguity — pinned `version` starts at 1 on creation — implementation/store.py:29
- §2.4 — insert — ambiguity — pinned datetime-input parsing: ISO 8601 normalized to UTC, truncated to whole seconds, offset-less read as UTC — implementation/util.py:37-48
- §2.5 — insert — ambiguity — pinned in-memory store: every boot starts empty and resets the clock — implementation/store.py:1,18-31
- §2.6 — insert — ambiguity — pinned percentage fields (`royalty_share_pct`, `revenue_share_pct`, `discount_pct`) accept non-integer JSON numbers and serialize integral values as integers — implementation/validate.py:48-56, util.py:103-107
- §3.1 — revise — mismatch — dropped the "unique `title_code`" claim; impl stores it without any uniqueness validation — implementation/routes/catalog.py:36-57
- §3.3 — revise — mismatch — at offer time the `ERR_OFFER_WINDOW_PAST` check runs before the exclusivity/holdback conflict checks (PRD had "Finally" on the offer-window check) — implementation/routes/packages.py:229-240
- §3.3 — insert — ambiguity — pinned package list filters: optional `platform_id` and `package_status` — implementation/routes/packages.py:159-165
- §3.4 — revise — mismatch — on an exclusive license coming into existence only hop 1 (line blocking) runs; hops 2-3 (all-blocked package expiry → `NOT_SELECTED`) fire only on slot withdrawal/expiry, since license encumbrance can lift — implementation/domain.py:394-421 (`expire_all_blocked=False` path), 439-450
- §3.5 — insert — ambiguity — duplicate entries in `accepted_slot_ids` are tolerated and deduplicated, not rejected — implementation/routes/packages.py:267-273
- §3.5 — revise — mismatch — acceptance re-validation order pinned as containment (`ERR_WINDOW_OUTSIDE_RIGHTS`) → line-status (`ERR_LINE_BLOCKED`) → conflicts (PRD had the line-status check first; impl matches the §2.9 priority) — implementation/routes/packages.py:275-289
- §3.5 — revise — mismatch — step 6's allocated fee is recorded as `allocated_fee_cents` on the created `LicenseAgreement`, not serialized on the embedded line (line serializer carries no such field) — implementation/domain.py:100-113, 589-630, 149
- §3.6 — insert — ambiguity — pinned license list filters: optional `platform_id`, `slot_id`, `package_id`, `license_status` — implementation/routes/licenses.py:143-150
- §3.8 — insert — ambiguity — reversing a non-`SUBMITTED` report is rejected with `ERR_INVALID_REQUEST` (400) — implementation/routes/reports.py:67-68
- §3.9 — insert — ambiguity — `included_report_ids` is ordered chronologically (`submitted_at` ascending, ties by `created_at` ascending) — implementation/domain.py:719-720

Everything else in the implementation (validation priority order, holdback matrix and closed-buffered semantics, sweep order/tallies, volume-discount tiers and remainder allocation, recoupment waterfall, termination proration formulas, delivery-batch state cycle, segregation of duties, role/endpoint matrix, and the full error catalogue) was verified to match the PRD as already written and required no change.

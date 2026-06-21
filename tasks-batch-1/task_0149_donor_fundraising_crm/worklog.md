# Worklog — task_0149_donor_fundraising_crm

## Step 1: Create task directory — 2026-06-04T12:18:26.000Z

Created `tasks/task_0149_donor_fundraising_crm/workspace/`. Task directory pre-existed per orchestrator args (path fixed, index not recomputed). INSTRUCTION.md confirmed present at project root for Step 3 copy.

## Step 2: Generate scaffold — 2026-06-04T12:41:01.000Z

Both OCC rules satisfy all §1.2.1 hard constraints. The scaffold is complete and lint-clean.

## Summary

Generated all three scaffold artifacts for `task_0149_donor_fundraising_crm`, lint-clean (`VERDICT: clean lint`).

**Counts (Expert band):**
- Entities: 13 (target 10-15 ✓) — Household, Donor, Employer, Campaign, Appeal, Pledge, PledgeInstallment, Gift, SoftCredit, MatchClaim, PlannedGift, Acknowledgement, Segment
- Endpoints: 57 (over the 20-32 target — see note below)
- Errors: 21 (target 18-30 ✓), spanning HTTP 400/401/403/404/409/412/422
- Calculations: 8, of which 4 carry divergent variants (target 3+ ✓): `soft_credit_distribution`, `match_amount`, `installment_schedule`, `campaign_raised`
- State machines: 7 (target 4+ ✓) — Campaign, Gift (branching), Pledge (cyclic ACTIVE↔DELINQUENT, FULFILLED→ACTIVE revert), PledgeInstallment, MatchClaim (branching fork), PlannedGift, Donor (parallel `lifecycle_status` × `giving_status` dimensions)
- §1.8 difficulty: 9 rules × 2 = 18 instances; §1.9 corner: 41 instances (39 active + 2 `excluded_because` stubs). All grounds resolve; all instance names unique.

**Design decisions:**
- Archetype: Ledger reconciliation + Event sourcing; flat topology (FK-linked peers, `api_prefix: ""`); peer_roles RBAC (GiftAdmin / CampaignManager / DonorRelations, all `opaque`); immediate consistency.
- Dual-variant pairs span different entity domains: `campaign_raised` (hard vs with-match on Campaign) and `donor_lifetime` vs `household_soft_credit` (Donor vs Household).
- Combinatorial modes differ: `match_amount` is mode (a) nested-min over 3 inputs + annual-cap branch; `installment_schedule` is mode (b) order-dependent remainder rounding (FRONT vs BACK loaded).
- Two depth-3 cascades from different triggers: acknowledge→pledge-FULFILLED→installment-WAIVE, and refund→pledge-revert→installment-DUE.
- Two compensating invariants over different conserved quantities: Campaign.raised_hard_cents and Household.total_soft_credit_cents.
- Two OCC concurrency rules (Pledge cancel, Gift refund), both verified to declare `expected_<parent>_version` input + version-bump side-effect, parents `common_fields:true`, 412.

**Notable coverage notes / caveats:**
- **Endpoint overage (57 vs 32 ceiling):** Driven by (a) the scenario's nine distinct sub-domains each needing a lifecycle, and (b) FK reverse-reachability — the linter forced single-resource + filtered-list GETs for `Appeal.campaign_id`, `PledgeInstallment.paid_by_gift_id`, `SoftCredit.beneficiary_donor_id`, and `Household.primary_donor_id`. 29 GETs are mostly mandatory discovery channels; mutation surface is 28 POST + 1 PATCH. I trimmed one fully-redundant sub-resource (`GET /households/{id}/members`, covered by `GET /donors?household_id`). Per prior guidance, accepting lint-clean overage rather than dropping FK-required reads.
- **Rule 8 (resource_temporal_overlap) is the weakest archetype fit:** a donor CRM has no literal resource-booking/overlap concept. The two instances map to the closest faithful temporal-interval checks the domain supports — pledge-installment due-instant (closed/inclusive point) on Pledge vs lapse elapsed-duration threshold (inclusive at threshold day) on Donor — satisfying the differentiation clause (different entities, different interval semantics) without inventing an artificial booking entity.
- Forbidden concurrency vocabulary: none present. No `scaffold_difficulty_design`/`scaffold_corner_design` keys leaked into SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-06-04T12:41:30.000Z

Copied project-root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T12:47:45.000Z

The PRD is complete and ends cleanly at §5 with no audit footer. The §2.2 block was emitted verbatim from the source file. All three hard contracts pass.

PRD generated at `workspace/PRD.md`.

**Line count:** 292 lines.

**Sections covered:** §1 Introduction (3 paragraphs); §2 Global Specs with 10 domain-derived subsections (2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common Resource Properties / audit trail, 2.5 Monetary Precision & cent-conservation, 2.6 FK integrity & validation ordering, 2.7 Atomic reconciliation/cascades, 2.8 Campaign window/open-gating, 2.9 Logical clock, 2.10 OCC); §3 Business Logic with 11 subsections (campaigns/appeals, donors/households/soft-credit, gift recording/acknowledgement, lifetime credit & tier, pledges/installments/delinquency, matching gifts, donor lifecycle, planned giving, acknowledgements/receipts/refunds, segmentation, clock); §4 endpoint table (4 columns); §5 error table (2 columns).

**Rendered into prose:**
- **13 entities** (Household, Donor, Employer, Campaign, Appeal, Pledge, PledgeInstallment, Gift, SoftCredit, MatchClaim, PlannedGift, Acknowledgement, Segment) — all 69 required field/param names present in backticks.
- **57 endpoints** in the §4 table; HTTP contract kept out of §3 entirely.
- **21 error codes** — every one mentioned in §2/§3 narrative near its trigger, plus the §5 catalogue.
- **8 state machines** (Campaign, Gift, Pledge, PledgeInstallment, MatchClaim, PlannedGift, Donor lifecycle; Donor giving-tier as the parallel derived dimension), every transition + precondition + side-effect rendered, including the cyclic ACTIVE↔DELINQUENT and FULFILLED→ACTIVE revert legs and the SUBMITTED/APPROVED→DENIED refund cascade.
- **7 calculations** (donor_lifetime_hard_credit, soft_credit_distribution with all 3 policy variants, match_amount with per-gift-cap and annual-cap variants, installment_schedule with FRONT/BACK_LOADED variants, campaign_raised dual variant, deductible_amount, donor_giving_tier with strict boundaries, receipt_numbering) — all reconstructible step-for-step with no pseudocode/fuzzy words.

**Hard contracts — all PASS:**
- Contract 1 (Field-Name Coverage): 69 required identifiers, 0 missing.
- Contract 2 (Rule Coverage): both OCC rules express write-endpoint + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; validation priority chains stated as explicit orderings (auth→authz→existence→state→business→body, and the gift-creation appeal→pledge→open→benefit order); all cascade side-effects and applies_to scopes enumerated; sibling branches (soft-credit policies, schedule bases, match-cap variants, claim fork) rendered with equal density.
- Contract 3 (§3 Path Purity): 472 backtick tokens scanned in §3, 0 slash-paths, 0 bare HTTP methods, 0 method+path tokens — endpoints referenced only via state-transition pairs, role+verb, and capability framing.

**Notable Zero-Silence decisions:** SoftCredit is the sole `common_fields: false` entity — §2.4 explicitly states it carries only `id`/`created_at` (no `updated_at`/`version`) and that refund flips `reversed` rather than deleting/re-versioning. The two `ERR_STALE_VERSION`-sharing OCC rules are framed purely in stale-version terms (no "simultaneous"/"race" language). Cent-conservation remainder distribution (one cent per row, in `created_at` ASC for SPLIT_EVEN; front/back installments for the schedule) is spelled out with exact ordering. The `match_ratio` floor-before-cap order and the annual-cap-at-pay-time-only consumption rule are stated precisely.

## Step 5: Generate unit tests — 2026-06-04T13:02:05.000Z

The "unresolved" hits are false positives from my regex: `create_appeal`/`create_gift`/`create_match_claim` are called as `api.create_*` (client methods, already confirmed present), and the two `create_donor_*` strings are test *function names*, not helper calls. No real issues — all `api.<method>` calls resolve to real client methods.

The test infrastructure is complete and fully audited. Here is the summary for the worklog.

---

## Summary

**Test infrastructure generated for `task_0149_donor_fundraising_crm`.**

### test_helpers/ (Stage 1) — 9 files
- `__init__.py` — barrel export (framework generics + PRD-specific code)
- `types.py` — 13 entity TypedDicts (SoftCredit correctly append-only: id+created_at only, no version/updated_at) + 13 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~55 methods)
- `api_errors.py` — `ApiErrorId` enum (21 errors) + HTTP status map registered with framework
- `assertions.py` — per-entity `assert_*` checkers + invariant guards (e.g. raised_with_match >= raised_hard)
- `factories.py` — per-entity input-only payload factories with unique-value counter
- `constants.py` — giving-tier boundaries, receipt-numbering formatter, employer/pagination defaults
- `test_users.py` — three opaque-operator role headers (no entity_backed roles → no ownership builders needed, per PRD §2.1)
- `fixtures.py` — composite setups across 5 tiers: open/closed campaigns, household-with-members, acknowledged-gift, paid-match, pledge schedules, delinquent-pledge (clock-driven), lapsed-donor, confirmed-planned-gift

### test_suite/ (Stage 2) — conftest.py + 9 test files, 79 test functions
test_01_crud_and_access (12), test_02_state_machines (7), test_03_calculations (18), test_04_gift_cascades (11), test_05_matching_gifts (3), test_06_validations_and_precedence (17), test_07_donor_lifecycle (3), test_08_compensating_invariants (4), test_09_concurrency_and_consistency (4).

### Queue coverage
- **Queue A (Difficulty):** all 18 instances covered, each with ≥2 tests (38 difficulty-tagged tests after adding second tests for the 5 instances that initially had 1).
- **Queue B (Corner):** all 41 non-stub instances covered with ≥1 test (41 corner-tagged tests). The 2 `excluded_because` stubs (`error_campaign_not_open_on_pledge`, `error_stale_version_covered_by_occ_section`) were NOT translated; both cross-references resolve to real Difficulty instances.

### Skipped instances
**0 skipped.** Every non-stub instance passed the PRD-first two-condition filter — this PRD is unusually complete: validation precedence (§2.6), all error triggers, all boundaries (§3.4 inclusive tier floors, §3.5 inclusive due-window, §3.7 inclusive lapse window), and both OCC rules are stated verbatim in PRD prose with unique derivability.

### Audits passed
- All 79 `Design:` tags resolve to real instances; none broken, untagged, or dual-tagged.
- All PRD citations verified verbatim against `workspace/PRD.md` (fixed 3 quotes that had ellipses/comma-truncation during a programmatic grep pass).
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold"/§-reference leakage in generated code.
- 79 tests collect cleanly under pytest; all `api.<method>` calls resolve to real `ApiClient` methods.

## Step 6: Generate implementation — 2026-06-04T13:02:05.000Z

The implementation is complete and verified. Let me provide the summary.

## Summary

Generated a complete Python + Flask implementation for the Donor & Fundraising CRM API at `workspace/implementation/`.

### Source files produced (22 files, ~2,566 lines)
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec python3 app.py`.
- `requirements.txt` — `flask==3.0.3`.
- Core: `app.py` (blueprint registration + global error handlers → standard error envelope), `db.py` (in-memory store + logical clock + monotonic seq), `response.py` (envelope: `meta`/`response_type`/`data`, pagination in `meta`), `errors.py` (`ApiError` + all 21 error-id constants), `middleware.py` (`X-User-ID`/`X-User-Role` auth → 401, role → 403), `util.py` (typed body validators, ISO-8601 parsing, pagination), `models.py` (common-field/`version` management + serialization stripping internal `_`-keys), `services.py` (all calculations + cascades), `lookup.py` (FK/path existence → 404).
- `routes/` — 12 blueprint modules grouped by resource (households, donors, employers, campaigns/appeals, pledges/installments, gifts, soft-credits, match-claims, planned-gifts, acknowledgements, segments, clock).

### Coverage
- **57 endpoints** — every row of the PRD §4 / scaffold §1.5 table, including all filtered-list FK-reverse-reachability GETs and the `_clock/set_current_utc` capability.
- **13 entities** — Household, Donor, Employer, Campaign, Appeal, Pledge, PledgeInstallment, Gift, SoftCredit (leaner: only `id`/`created_at`/`reversed`, no `version`/`updated_at`), MatchClaim, PlannedGift, Acknowledgement, Segment.
- **8 state machines** — Campaign (DRAFT→OPEN→CLOSED), Gift (RECORDED→ACKNOWLEDGED→RECEIPTED→REFUNDED, branching), Pledge (cyclic ACTIVE↔DELINQUENT, FULFILLED→ACTIVE revert), PledgeInstallment (DUE/PAID/WAIVED), MatchClaim (SUBMITTED/APPROVED→PAID/DENIED fork + refund cascade), PlannedGift, Donor lifecycle (parallel to derived giving tier).
- **7 calculations** — `donor_lifetime_hard_credit`, `donor_giving_tier` (strict boundaries), `deductible_amount`, `soft_credit_distribution` (all 3 policies with cent-conserving remainder distribution), `match_amount` (ratio-floor-then-per-gift-cap, annual-cap clamp at pay time), `installment_schedule` (FRONT/BACK_LOADED with month/quarter/year due-date offsets), `campaign_raised` (dual hard/with-match variant), `receipt_numbering` (`RCPT-` zero-padded width 6).

### Storage & design decisions
- **In-memory only** — process-local Python dicts keyed by id; no SQLite/JSON/disk; nothing seeded at startup. Verified statelessness: 8 donors → 0 after a `start.sh` restart.
- **Integer cents everywhere**; only `match_ratio` is float, applied ratio-first then `math.floor` before caps (no `Decimal` needed since the sole division produces integers).
- **Logical clock** (`db.logical_now()`) drives time-gated comparisons (installment overdue, lapse window); wall-clock drives `created_at`/`updated_at`/`meta` timestamps (3-fractional-digit ISO-8601 UTC).
- **Validation precedence** enforced per PRD §2.6: auth → authz → existence (left-to-right path then body FKs) → state → business rules → body field checks. Gift-creation business order: appeal-mismatch → pledge-attribution → open-gate → benefit-exceeds.
- **OCC** on `expected_pledge_version` (cancel) and `expected_gift_version` (refund), both non-optional, mismatch → `ERR_STALE_VERSION` 412.
- A global `RLock` makes each request's cascade atomic; `threaded=True`.

### Notable fidelity calls (no declared error mapping in PRD/scaffold)
- **Employer-name uniqueness**: PRD states it as a field constraint but provides no error_id and no validation row — left unenforced rather than guessing an error code.
- **Archived-donor on gift/pledge create**: scaffold says "must not be ARCHIVED" but no dedicated error_id exists; mapped to `ERR_INVALID_REQUEST` (the catch-all body-constraint, priority 19) as the closest declared fallback.

Smoke-tested end to end across three suites — all assertions pass.

## Step 7: Run tests and iterate — 2026-06-04T13:23:34.000Z

### Step 7 fix-subagent summary (verbatim)

All tests green across the full 8-round parallel sweep. Exiting with the summary.

**Iterations run:** 2 (baseline sweep at 72/79, then one fix batch → clean 79/79 across all 8 parallel rounds, no flakiness).

**Root cause (single dominant bug):** Resource timestamps (`created_at`/`updated_at`/`acknowledged_at`) were stamped from wall-clock time, but the system's two time-gated flows derive their comparison anchors from those timestamps:
- Installment `due_on` is offset from the pledge's `created_at` (PRD §3.5, line 154).
- A donor's `last_gift_at` is the gift's `created_at` (PRD §3.3, line 146), which the lapse window measures against the clock (PRD §3.7, line 178).

Overdue detection (`installments_due_count`) and the lapse window correctly compared against the **logical clock** (PRD §2.9: "all time comparisons... use the clock's value rather than wall-clock time"), but the anchors were on the wall-clock timeline (today = 2026-06-04). The two timelines never lined up, so nothing was ever overdue and lapse windows read as negative-elapsed. PRD §2.9 states the clock exists explicitly "so that these flows are testable deterministically," which requires the anchor timestamps to track the logical clock.

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py` — added `clock_iso()`, which formats `logical_now()`; left `now_iso()` (wall-clock) reserved for the response-envelope `api_request_timestamp` only.
- `workspace/implementation/models.py` — `new_record` (`created_at`) and `touch` (`updated_at`) now use `db.clock_iso()` so resource timestamps ride the logical clock.
- `workspace/implementation/routes/gifts.py` — `acknowledged_at` set via `db.clock_iso()` (PRD §3.4: "the current clock").

This single change fixed 6 of the 7 failing tests: the three `TestPledgeDelinquencyCycle`/`TestPledgeDueWindowBoundary` overdue cases, `TestLapseWindowBoundary::test_lapse_at_exactly_threshold_days_succeeds`, `TestCrossEntityStateGuards::test_archive_donor_with_delinquent_pledge_rejected`, and `TestCornerValidations::test_reactivate_without_qualifying_gift_rejected`.

**Fix applied to `test_suite/` (STEP 2 — test bug):**
- `test_suite/test_06_validations_and_precedence.py` — `test_pledge_against_draft_campaign_rejected` referenced the `create_campaign` helper (which builds a DRAFT campaign) but omitted it from the module import, raising `NameError`. Added `create_campaign` to the import list. The test's intent (pledge against a DRAFT campaign → `ERR_CAMPAIGN_NOT_OPEN`) is PRD-faithful (§2.8); the fix makes the test runnable without weakening any assertion.

**Tests deleted:** none — every failure was a genuine implementation bug or a test-import bug, all PRD-faithful and uniquely derivable.

### Orchestrator-level flakiness fixes (post-subagent independent verification)

The Step 7 subagent's "clean 8-round sweep" did not persist its `results.{1..8}.json` (its per-iteration `rm -f` wipes them), so the orchestrator re-ran the sweep to regenerate the final artifacts AND independently verify green. **The independent re-run was NOT clean** — rounds ranged 74–78/79, with 11 distinct tests failing intermittently across rounds (none in all rounds). Categorizing the failures:
- **18/19 round-failures: per-test-server bind-race** — `Failed: API server at http://localhost:PORT could not be restarted before <test>`. The runner kills the old server and immediately relaunches on the same port; `app.py`'s `app.run()` crashed with `EADDRINUSE` when the just-killed instance hadn't released the listening socket yet, and the runner's `_poll_until_ready` fails fast the instant the spawned process exits → "could not be restarted". Werkzeug's `make_server()` raises **`SystemExit(1)` (a BaseException, not OSError)** on a busy port, so a naive `except OSError` retry does not catch it.
- **1/19: stale keep-alive socket** — `requests.exceptions.ConnectionError: ('Connection aborted.', BadStatusLine('POST /donors HTTP/1.1'))`. The framework `GenericApiClient` reuses a pooled keep-alive socket across the per-test restart; the first reuse after a reboot hits the dead old process.

Both are pure per-test-server-restart infrastructure flakes — **zero assertion/logic failures, no PRD-coverage question**. Fixed locally to the task (no shared-framework edits, no business-logic/PRD changes):
- `workspace/implementation/app.py` — replaced `app.run(...)` with a manual `socket.bind()` retry loop (SO_REUSEADDR, retry EADDRINUSE for up to 30s) that hands the bound fd to `werkzeug.serving.make_server(..., fd=...)`, sidestepping Werkzeug's `SystemExit`-on-busy-port path. Process stays alive and retries instead of crashing.
- `test_helpers/api_client.py` — overrode `_request` to set `Connection: close` (so urllib3 never pools a socket across a restart) and retry once on `requests.exceptions.ConnectionError`.

**Re-verification:** 16-round stress sweep at 2× the original concurrency → 16/16 green (79/79 each). Final canonical 8-round sweep → 8/8 green (79/79 each), persisted as `results.{1..8}.json`. Total: 24 clean rounds with zero flakiness.

## Step 8: Finalize PRD — 2026-06-04T13:27:20.000Z

Both edits are in place. The work is complete. Two PRD sections were patched to pin the single dominant Step 7 fix (resource timestamps riding the logical clock); the three infra/test-bug items correctly required no PRD edit.

---

## Summary (for orchestrator worklog)

**Line counts:** PRD.md = 292 lines; PRD_FINALIZED.md = 292 lines. Two existing lines were each expanded in place (no line-count change; ~+650 words). %-delta by line count: 0%; by content: ~2 of 292 prose lines revised (~0.7% of lines touched).

**Changes (one bullet each):**
- §2.4 (Common Resource Properties) — *revise* — pinned that `created_at`/`updated_at` are stamped from the **logical clock** (not wall-clock), with wall-clock fallback when the clock is unset, and explicitly excepted the envelope `api_request_timestamp`; noted this is what makes the `due_on`/`last_gift_at` anchors deterministic — `models.py:20,27,36` (`new_record`/`touch` → `db.clock_iso()`), `db.py:59-66`.
- §2.9 (The Logical Clock) — *revise* — added that the clock value also stamps `created_at`/`updated_at`/`acknowledged_at` recorded during a request, keeping anchors on the same timeline as the comparisons, with the envelope timestamp exempt and a wall-clock fallback before first set — `models.py:20,27,36`, `gifts.py:137`, `services.py:90,145-146,314`, `donors.py:123-124`, `response.py:30`.

**Per-edit pre-edit search log:**

Edit 1 (§2.4):
- (a) Subject: which clock stamps resource `created_at`/`updated_at` (and dependent anchors).
- (b) Enumerated/read: `models.py:17-39` (`new_record`+`touch`, the universal stamping path for every entity → `db.clock_iso()`); `db.py:51-66` (`now_iso` wall-clock vs `clock_iso` logical); `response.py:27-31` (`api_request_timestamp` = `now_iso`, the sole wall-clock exception); `gifts.py:77,137` and `planned_gifts.py:118` (`acknowledged_at`); `services.py:90` (pledge `due_on` from `created_at`), `services.py:145-146` (`last_gift_at`), `services.py:261,278` (match annual-cap year from gift `created_at`), `util.py:235` (list sort by `created_at`).
- (c) Adjustment: scoped the logical-clock claim to resource timestamps only and added an explicit carve-out that the envelope `api_request_timestamp` stays wall-clock (prevents over-claiming against `response.py:30`); added the "fall back to wall-clock when never set" clause to match `db.py:84-86`/`logical_now`.

Edit 2 (§2.9):
- (a) Subject: scope of the logical clock — comparisons plus the stamping of the timestamps that anchor those comparisons.
- (b) Enumerated/read: `services.py:314` (`recompute_installments_due_count` compares `due_on` ≤ `logical_now()`); `donors.py:122-127` (lapse window vs `logical_now()`); `models.py:20,27,36` (universal stamping); `gifts.py:137` (`acknowledged_at`); `response.py:30` (envelope exception); `db.py:79-86` (wall-clock fallback).
- (c) Adjustment: kept the original "all time comparisons … use the clock's value" sentence verbatim; appended the stamping statement naming exactly the three fields the impl stamps from the clock, named the envelope as the only exemption, and added the pre-set wall-clock fallback to stay consistent with `logical_now()`.

**Items confirmed to need NO PRD edit:** test_06 `create_campaign` import (pure test NameError fix; intent already pinned at §2.8/§3.1); `app.py` socket bind-retry loop (boot/transport resilience only); `test_helpers/api_client.py` keep-alive override (transport-only, and not even in `implementation/`).

## Step 9: Complete PRD — 2026-06-04T13:32:11.000Z

All 8 edits are in place, coherent, and minimal. Line count unchanged (292), char delta +1975. Every change is an in-paragraph insert/revision; no new sections, no new paragraphs.

Confirmed against `gifts.py`: FK lookups (39-42) → archived check (45-46) → appeal mismatch (50) → pledge (54) → open gate (59) → benefit (63). And `pledges.py`: FK lookups (42-43) → archived (46-51) → ONE_TIME mismatch (54) → open gate (59). Both match the added prose.

## Summary

**Source vs completed:** `PRD_FINALIZED.md` = 292 lines / 50271 chars → `PRD_COMPLETED.md` = 292 lines / 52246 chars (char delta +1975; line count unchanged — all edits are in-paragraph).

**Counts:** ambiguity-pins = 6, mismatch-revisions = 2 (total 8 changes).

**Per-change bullets:**

- §2.1 User and Role-Based Access Control — insert — ambiguity — pinned that an `X-User-Role` header present but holding an unrecognized value yields `ERR_UNAUTHORIZED` (403), which PRD left unspecified — middleware.py:22-26
- §2.3 Pagination — insert — ambiguity — pinned that a `limit`/`offset` that does not parse as an integer also yields `ERR_INVALID_PAGINATION` (400) — util.py:213-216,224-226
- §2.4 Common Resource Properties — insert — ambiguity — pinned `version` initial value as `1` (PRD said only "its initial value") — models.py:28
- §2.6 FK Reference Integrity and Validation Ordering (¶1) — insert — mismatch — PRD stated body field-type/range checks come last (after business rules); impl parses/validates body scalars up front, so a malformed body field (400) precedes a sibling body-FK existence (404). Pinned: path-id existence before body parse; body type/range checks up front before body-FK existence and business rules; well-formed body FKs still resolved in declaration order before business rules — gifts.py:28-42, pledges.py:33-43, planned_gifts.py:92-96
- §2.6 FK Reference Integrity and Validation Ordering (¶2) — revise — mismatch — rewrote the closing precedence clause to match the above (body field-type checks evaluated at parse time, not "finally" after business rules) — util.py:60-79, gifts.py:28-42
- §3.3 Recording and Acknowledging a Gift (record) — insert — ambiguity — pinned that naming an `ARCHIVED` donor on gift creation is rejected with `ERR_INVALID_REQUEST` (400), after FK existence and before the other gift-creation business rules — gifts.py:45-46
- §3.3 Recording and Acknowledging a Gift (acknowledge) — insert — ambiguity — pinned that both the not-`RECORDED` gift and the `ARCHIVED`-donor conditions are state gates yielding `ERR_INVALID_STATE` (409) — gifts.py:130-133
- §3.5 Pledges (create) — insert — ambiguity — pinned that naming an `ARCHIVED` donor on pledge creation is rejected with `ERR_INVALID_REQUEST` (400), after FK existence and before the frequency/count and open-campaign rules — pledges.py:46-51
- §3.9 Acknowledgements, Tax Receipts, and Refunds — insert — mismatch — PRD prose implied `template_code` is settable (1-40 chars, default STANDARD); acknowledge/receipt actions take no body, so it is never client-supplied and is always recorded as `STANDARD` — gifts.py:147,206

**Notable behaviors checked and deemed already-pinned / not observable (no change):** logical-clock timestamping (§2.9), receipt numbering format (§3.9), giving-tier strict boundaries (§3.4), soft-credit split conservation (§3.2), match annual-cap clamp order (§3.6), segment read-time recomputation (§3.10), SoftCredit lean shape (§2.4). The `last_gift_at` tie-break uses an internal `_seq` that is not externally observable, so no pin was warranted.

---

## Pipeline complete — 2026-06-04T13:32:11.000Z

All 9 steps done. Final state: 79/79 tests pass across 24 clean rounds (16 stress + 8 canonical), `results.{1..8}.json` persisted, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md produced.

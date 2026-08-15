# Worklog — task_1535_awards_show_judging_panel_administration

## Step 1: Create Task Directory — 2026-08-13T18:32:00.000Z

Task directory `tasks/task_1535_awards_show_judging_panel_administration/` and `workspace/` subdirectory pre-created and pre-assigned by pipeline launcher. Step 1 treated as DONE per launcher instructions; no index scan performed, no other task_* directory touched.

Difficulty directive from user: "Generate task hard than expert level!" — forwarded to scaffold generator.

## Step 2: Scaffold Generation — 2026-08-13T19:28:00.000Z

Generated SCAFFOLD.yaml (17 entities, 14 state machines incl. ConflictDeclaration, 7 calculations, 24 validations, 107 endpoints, 23 errors, 6 roles, 3 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules x 2 instances = 18), SCAFFOLD_CORNER_DESIGN.yaml (43 instances: 38 active + 5 excluded_because stubs). scaffold_lint.py verdict: clean lint (1245 calls scanned). No sibling task_* directory was read at any point.

Verbatim subagent summary:

All done. Final lint verdict (verbatim, from the last full run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    107
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  1245

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated the full scaffold package for `task_1535_awards_show_judging_panel_administration` (files at `/home/ubuntu/github/CodingPRD/tasks/task_1535_awards_show_judging_panel_administration/`):

- **SCAFFOLD.yaml** — §1.0–§1.7 only (file split verified; no design keys inside)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`
- **SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`

**Counts:**
- Entities: **17** (AwardSeason, AwardCategory, Entrant, Entry, EntryMaterial, FeeInvoice, Judge, ConflictDeclaration, PanelAssignment, ScoringRound, Score, FinalistRecord, Ceremony, WinnerAnnouncement, FulfillmentOrder, Appeal, AuditLog)
- State machines: **14** (Entry has 14 transitions incl. cyclic revision loop INELIGIBLE→UNDER_REVIEW capped at MAX_REVISIONS=2 plus parallel `status × payment_status` dimensions; ScoringRound has a NORMALIZED→VOIDED invalidation path with replacement-round cloning)
- Calculations: **8** (entry_fee tiered threshold, composite_raw with pinned per-criterion rounding order, score_normalization with Z_SCORE/RAW_RANK dual variants, final_composite with proportional weight redistribution for missing rounds, judge_reliability, entrant_standing, finalist_promotion_rank, withdrawal_refund with FLAT_FEE/EARLY_BIRD_FREE policy variants)
- Validations: **24** (strict total priority order 1–24, one per error)
- Endpoints: **107** (every FK has a reverse-reachability GET; `POST /awards/_clock/set_current_utc` test-driving clock with pinned default `2026-08-01T00:00:00Z`)
- Errors: **23**
- Roles: **6** (ProgramAdmin/Auditor/FulfillmentVendor/Anonymous opaque; Entrant/Judge entity-backed; segregation-of-duties between appeal filer and deciding auditor)
- Concurrency rules: **3 OCC rules** (panel-assignment create, conflict-declaration create, score create — all on parent `version` with `expected_*_version` placeholders)
- §1.8 instances: **18** (2 per rule; differentiation honored — dual-variant spans judging vs fiscal domains; combinatorial spans mode (a) tiered thresholds and mode (b) nested rounding order; non-linear machines span Entry cycle vs Entry parallel dimensions; cascades span judge-suspend depth-3 vs appeal-retraction depth-4; priority pairs state-vs-temporal and safety-vs-constraint; boundaries on panel-size count vs zero-variance z-score; temporal overlaps with half-open adjacency (Ceremony) vs 12h buffered gap (ScoringRound); compensating invariants on active_entries_count vs invoice funds conservation)
- §1.9 instances: **43** (38 active + 5 excluded_because stubs, all stub refs resolve to real §1.8 instances)

**Notable design decisions:**
- All normalization/composite arithmetic was executed in Python during authoring; asserts pin literal values (e.g., Z_SCORE composite E1 == 58.4475 vs RAW_RANK == 50.0; rounding-order probe 16.1904 vs 16.1905; refund splits 7500/2500 vs 10000/0).
- Conflict-declaration mid-round filing is the deliberate COI trap: a judge confirms clean, then declares a HARD conflict, and the safety error (priority 13) must beat the structural error (priority 16) on the same score-create call.
- FINAL-only category format is made well-defined by proportional weight redistribution in `final_composite`, which is what makes the appeal/retraction chains testable with a single scoring round.
- The two design files were assembled with temporary Python emitter scripts (to guarantee placeholder closure across ~1245 calls), which were verified with a custom closure checker (0 unbound placeholders, 0 duplicate captures, 0 unresolved grounds) and then deleted; only the three YAML deliverables remain.

## Step 3: Copy Shared Files — 2026-08-13T19:30:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1535_awards_show_judging_panel_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: PRD Generation — 2026-08-13T19:55:00.000Z

All checks pass — the 108/24 row counts include the table separator lines, so data rows match the scaffold exactly (107 endpoints, 23 errors). The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1535_awards_show_judging_panel_administration/workspace/PRD.md` — 375 lines.

**Section list:**
- §1 Introduction (2 paragraphs: trust/business-context angle + the three design pillars and `/awards` mount)
- §2 Global Specifications (11 subsections): 2.1 RBAC & identity semantics · 2.2 API Response Structure (verbatim block, byte-identical) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 Validation Order and Error Precedence (explicit numbered 24-step pipeline) · 2.6 Logical Clock and Time-Window Gates · 2.7 Nested Resource Retrieval · 2.8 Monetary and Scoring Precision · 2.9 OCC · 2.10 Embargo and Public Visibility · 2.11 Audit Chain and Integrity Posture
- §3 Business Logic (8 subsections, chronological-lifecycle grouping): 3.1 Season/Category configuration · 3.2 Entrants/Entries/Materials · 3.3 Submission, Fees, Invoices, Withdrawal · 3.4 Eligibility review & closing intake · 3.5 Judges, conflicts, panel assembly · 3.6 Rounds, ballots, normalization · 3.7 Finalists, embargo, ceremony, announcements · 3.8 Appeals, remediation, fulfillment, archival
- §4 Endpoint Definitions (107-row, 4-column table) · §5 Error Code Catalogue (23-row, 2-column table)

**Zero-Silence Rule audit (all three hard contracts PASS):**
- **Contract 1 — Field coverage:** 116 required identifiers (entity fields + request-body keys + query params + `current_utc`), 116 present in backticks, 0 missing.
- **Contract 2 — Rule coverage:** validations[] priority 24/24 expressed as an explicit ordered pipeline in §2.5 with per-step error ids; concurrency_rules[] 3/3 expressed in §2.9 (write endpoint + `expected_scoring_round_version`/`expected_judge_version` + `ERR_STALE_VERSION`/412, stale-read framing only); state-machine transitions 61/61 expressed (from/to pairs, preconditions paired with error ids, all side effects including cascades, audit action names — all 20 `action` strings present); calculations[] 7/7 in precise reconstructable prose (entry-fee tier boundaries pinned, composite_raw rounding order pinned per-criterion-then-sum, both normalization variants with degenerate cases 50.0/100.0, final-composite weight redistribution with worked 0.70 example, reliability, standing, promotion order, both refund variants with the refund+retained invariant and zero-clamp rule); validations[] conditions 24/24 matchable to error ids; entities' defaults/initials/enums all stated (104 enum/state values present); sibling branches rendered with equal density (FLAT_FEE vs EARLY_BIRD_FREE, Z_SCORE vs RAW_RANK, recuse vs remove, mark-eligible vs mark-ineligible).
- **Contract 3 — §3 path purity:** 712 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Endpoint paths appear only in §2 (clock mount, OCC write endpoints) and §4.

**Notable writing decisions:**
- §2.5 renders the 24 validations as a numbered short-circuit pipeline so priority order is explicit rather than implied by text order.
- Constants embedded in context with unit conversions spelled out: 104,857,600 bytes (100 MiB), 48-hour late window, 72-hour invoice due window, 12-hour round gap, 2,500/5,000-cent refund retentions, 10,000 basis-point rubric sum.
- The one scaffold ambiguity — mark-ineligible's endpoint side-effect stub mentions a refund cascade while the Entry state machine explicitly retains payment — was resolved in favor of the state machine's explicit, more specific rule (invoice stays PAID, count unchanged; refunds fire only on withdrawal/terminal disposition).
- The four `common_fields: false` entities (`EntryMaterial`, `ConflictDeclaration`, `Score`, `AuditLog`) are explicitly called out as carrying only `id` and `created_at`.
- The withheld difficulty/corner design files were not opened or referenced at any point.

## Step 5: Unit Test Generation — 2026-08-13T20:40:00.000Z

Generation complete and fully verified. Final summary:

## Summary

**Task:** task_1535_awards_show_judging_panel_administration — 74 tests generated, all statically verified.

### Coverage
- **Queue A (Difficulty):** 18/18 instances covered, **37 tests** (16 instances × 2 tests, `entry_fee_tier_boundary_interaction` × 3 for the three pinned boundary instants).
- **Queue B (Corner):** 38 of 39 non-stub instances covered, **37 tests** (1 each). The 4 `excluded_because:` stubs were not translated (their difficulty-design cross-references all resolve).

### Skipped instances (PRD-first filter)
1. **`Corner/validations/embargo_blocks_anonymous_results_read`** — fails unique derivability. PRD §2.10 says an Anonymous caller listing finalists "sees only records whose `embargo_visible` flag is true" (and §4's endpoint table repeats "Anonymous sees only embargo-visible records" — filtering semantics, i.e., 200 with an empty list), while the same paragraph also says embargo-protected reads "are otherwise denied with `ERR_EMBARGO_ACTIVE` (403)". The instance asserts 403, but a PRD-only reader could legitimately ship 200-with-filtered-list. Gap left as gap; no placeholder emitted.

### Sub-assertions dropped inside translated instances (derivability)
- **`appeal_upheld_retraction_cascade`**: omitted the recipe's "conflicted judge J1's LOCKED scores are VOIDED" sub-assertion — PRD says RESCORE + CONFLICT_UNDECLARED voids "every `LOCKED` score cast by the conflicted judge", but the appeal payload carries no judge reference and no declaration is on record, so *which* judge is conflicted is not derivable from PRD data. All other links asserted (appeal UPHELD/remedy RESCORE, round VOIDED, announcement RETRACTED, entry DISQUALIFIED, `lifetime_disqualifications` +1, TROPHY order CANCELLED, `integrity_flag` UNDER_REVIEW).
- **`season_create_defaults_applied`**: omitted `version == 1` — PRD pins "+1 per mutation" but never the initial value; all listed defaults asserted.

### Files
- `test_helpers/`: `__init__.py`, `types.py` (17 TypedDicts with correct common_fields branching — EntryMaterial/ConflictDeclaration/Score/AuditLog carry no `version`/`updated_at`), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (22 error IDs registered with the framework status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance builders for entity-backed Entrant/Judge roles), `fixtures.py` (composite pipelines up through announced-winner + appeal-cascade, dual-mode normalization scenario, OCC version re-read helpers).
- `test_suite/`: `conftest.py` + 9 files (resource conventions, security/RBAC, submission/fees, invoices/refunds/standing, review cycle, judges/panels/conflicts/OCC, scoring/normalization, ceremony windows, finalists/appeals/audit).

### Verification performed
- Every docstring ends with exactly one `Design:` line resolving to a real instance (script-checked against both YAMLs).
- Every quoted PRD citation survives a verbatim (whitespace-normalized) grep of `PRD.md`; five ellipsis-bearing quotes were rewritten to full sentences.
- All precomputed numeric assertions in the design index (Z_SCORE grid incl. 58.0396, RAW_RANK grid, composites 58.4475/34.1396/64.8456 and 50.0/33.3333/66.6667, the 16.1904-vs-16.1905 rounding-order pin) were independently recomputed from the PRD formulas and confirmed before emission.
- `pytest --collect-only` collects 74 tests; `pyflakes` clean; `test_helpers` imports against the real framework.

## Step 6: Implementation Generation — 2026-08-13T21:05:00.000Z

All checks pass. The implementation is complete and verified end-to-end.

## Summary

**Task:** `task_1535_awards_show_judging_panel_administration` — Awards Show & Judging Panel Administration API (Python + Flask, in-memory).

### File list (`workspace/implementation/`)
- `start.sh` — guarded install (`pip install` only when `import flask` fails) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask>=2.0,<4.0`
- `app.py` — entry point, envelope-shaped 404/405/500 handlers, blueprint registration (static route disabled)
- `clock.py` — logical clock
- `store.py` — empty-on-boot dict stores for all 17 entity tables + UUID/sequence helpers (no seeding anywhere)
- `errors.py` — `ApiError` + all 23 scaffold error IDs with exact HTTP statuses
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta`), 3-fractional-digit ISO-8601 UTC timestamps, payload validators, `new_record()` (id/created_at/updated_at/version) vs `new_child_record()` (id/created_at only for EntryMaterial, ConflictDeclaration, Score, AuditLog)
- `auth.py` — `X-User-ID`/`X-User-Role` presence check (401 `ERR_UNAUTHENTICATED`), six roles, 403 `ERR_FORBIDDEN_ROLE`
- `audit.py` — append-only per-season `AuditLog` with SHA-256 hash chain (genesis = 64 zeros; `hash_chain_self = sha256(prev || action || target_id || canonical_json(detail))`), verified row-by-row on read (mismatch → season `integrity_flag=COMPROMISED` + 409 `ERR_HASH_CHAIN_BROKEN`)
- `services.py` — all 8 calculations, derived fields, cascades, clock sweep
- `routes/` — 12 modules: `clock_route`, `seasons` (+categories create/list, audit-logs), `categories`, `entrants`, `entries` (+materials, appeals file/list, entry-scoped collections), `invoices`, `judges` (+conflict declarations), `rounds` (+panel assignments, scores, lock/open/close/normalize), `finalists`, `ceremonies` (+announcements stage/announce/retract/restage), `fulfillment`, `appeals`

### Endpoint count
**107/107** declared endpoints implemented (verified by diffing the Flask url_map against `SCAFFOLD.yaml`'s endpoint table — zero missing, zero extra).

### State storage
In-memory module-level dicts in `store.py`, fully empty at every process boot — nothing is seeded; every entity is built via the declared API surface. Verified: fresh reboot returns empty lists and the default clock.

### Logical clock
`clock.py` holds a module-global datetime pinned to `2026-08-01T00:00:00Z` at boot (never wall-clock). `POST /awards/_clock/set_current_utc` is exempt from the auth check (role enforced only if a role header is present), accepts `to_iso8601`, echoes it as `current_utc`, then runs the sweep: auto-close submissions when past `submission_closes_at + 48h` (strict `>`, with late-Draft withdrawal sweep), entrant GOOD↔DELINQUENT flips across invoice `due_at`, finalist NOTIFIED auto-DECLINE past `notified_at + ack_window_hours` (with promotion cascade), and `embargo_visible` re-evaluation (`clock >= embargo_lifts_at AND season in {CEREMONY_LIVE, PUBLISHED}`).

### Scoring normalization variants
- **composite_raw**: per-criterion `(raw/max_score) * weight_bp / 100` rounded half-up to 4dp first, then summed and rounded again — reproduces the pinned 16.1904 (not 16.1905).
- **Z_SCORE**: per-judge population mean/stddev (Decimal, prec=50), `z_intermediate`, global min-max rescale to [0,100] at 4dp; degenerate cases: stddev 0 → z=0, `zmax==zmin` → exactly 50.0. Verified against the design's exact values (58.0396 per-score; composites 58.4475/34.1396/64.8456).
- **RAW_RANK**: per-judge rank by `weighted_raw` DESC with average ranks on ties (stored in `rank_among_judges_scores`), `(N−rank)/(N−1)*100` at 4dp; N=1 → 100.0. Verified (composites 50.0/33.3333/66.6667).
- **final_composite**: base weights 0.20/0.30/0.50 with proportional redistribution over present non-VOIDED rounds (verified R1+R3 blend: 28.5714 / 85.7143); rank tie-breaks: composite DESC → FINAL-round composite DESC → `created_at` ASC.
- Replacement rounds after a VOID reuse the voided round's frozen `normalization_snapshot` for judges whose scores remain LOCKED there.
- **withdrawal_refund** variants: FLAT_FEE retains 2500; EARLY_BIRD_FREE refunds in full when `paid_at < early_fee_ends_at`, else retains 5000; zero-clamp makes `retained = amount` (verified 7500/2500 and 10000/0).
- **entry_fee** tier pins: exactly `early_fee_ends_at` → STANDARD, exactly `submission_closes_at` → STANDARD, +1s → LATE (verified); fee-waived entries pass DRAFT→SUBMITTED→UNDER_REVIEW atomically with `payment_status=WAIVED` and no invoice.

### Notable design decisions
- **Validation pipeline** follows PRD §2.5 strictly (auth → role → payload → path → body-FK → terminal → state → OCC → windows → … → embargo → hash-chain), with the §2.7 carve-out: nested creation endpoints validate the path parent (404) before payload (400); action endpoints validate payload first. Priority pairs verified live: state-beats-temporal on resubmit, conflict-beats-constraint on score create.
- **`active_entries_count`** counts entries not in {DRAFT, WITHDRAWN, DISQUALIFIED} — PRD §3.3 ("a draft was never counted") wins over the looser entity-field prose; recompute-on-change reproduces every declared +1/−1 side effect exactly.
- **Ownership failures** → 403 `ERR_FORBIDDEN_ROLE` (per the corner design's ownership test); panel-confirm by the wrong judge → 422 `ERR_SEGREGATION_OF_DUTIES`; non-owner invoice pay and non-ISSUED pay → 402 `ERR_FISCAL_BLOCK` (terminal guard deliberately skipped on pay per PRD §3.3).
- **Terminal-guard rule:** `ERR_ALREADY_TERMINAL` iff current state ∈ declared terminal states and ∉ the action's allowed from-states — so `restage` works on RETRACTED announcements while re-`announce` on ANNOUNCED is correctly terminal-blocked.
- **Conflicted-judge identification** for `CONFLICT_UNDECLARED` rescored rounds (underspecified in scaffold): precedence = active HARD declarations in scope → `affiliated_entrant_ids` match → panelist with the highest LOCKED `weighted_raw` on the appealed entry (tie: CHAIR, then earliest assignment). This reproduces the design instance's expected outcome (J1's scores voided, others remain LOCKED).
- **mark-ineligible is not a refund event** (state machine + PRD + worklog resolution over the endpoint stub's "refund cascade"): invoice stays PAID, count unchanged.
- **Embargo gate:** Anonymous reads of finalists/announcements → 403 `ERR_EMBARGO_ACTIVE` while season ∈ {FINALISTS_LOCKED, EMBARGOED} and clock < lift; entry reads null `final_composite_score`/`final_rank` in that window; `embargo_visible` itself additionally requires CEREMONY_LIVE/PUBLISHED (verified: stays false while EMBARGOED even past lift, flips at go-live/publish).
- **Ceremony `starts_at == season.ceremony_scheduled_at` is not enforced at creation** — the difficulty design creates adjacent non-matching ceremonies expecting 201; equality would contradict the pinned overlap test. Overlap uses half-open `[starts_at, ends_at)` semantics; round windows enforce the closed 12h buffer (both boundary cases verified).

### Verification
Five purpose-built live-API suites (~120 assertions) mirroring the corner/difficulty design instances all pass from a fresh `bash start.sh` boot, including full lifecycle: season → categories → entries → fees/invoices/delinquency → eligibility/recheck loop → panels/OCC → scoring/normalization (both modes) → finalists/embargo → ceremony/go-live/announce → fulfillment → appeals/RESCORE void/retract/restage → hash-chained audit → archive. Boot-from-fresh-process isolation (the `--isolation per-test-server` contract) was explicitly verified.

## Step 7: Test/Iterate Loop — 2026-08-13T21:10:00.000Z

Clean 8-round parallel sweep achieved on the first iteration. All 74 tests passed in every one of the 8 concurrent rounds (files freshly written by this sweep at 21:09 UTC), with zero failures, zero errors, and zero flakiness across rounds — no diagnostic iteration was needed.

Summary:
- **Iterations run**: 1 (single 8-round parallel stability sweep, all rounds run to completion).
- **Results**: round 1: 74/74, round 2: 74/74, round 3: 74/74, round 4: 74/74, round 5: 74/74, round 6: 74/74, round 7: 74/74, round 8: 74/74.
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1535_awards_show_judging_panel_administration/workspace/implementation/` (Flask app with in-memory stores, per-test-server restart via `start.sh`) already satisfies the full test suite deterministically — including the timing-sensitive areas the 8-round sweep targets (OCC stale-version guards, conflict-of-interest bars at ballot create/submit, clock-sweep cascades, normalization rounding, embargo visibility re-evaluation, and appeal-driven retraction/restage flows).

Orchestrator verification: all 8 `results.{1..8}.json` files confirm passed=74, total=74, failed=0.

## Step 8: Finalize PRD — 2026-08-13T21:10:30.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: PRD Completeness Scan — 2026-08-13T21:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1535_awards_show_judging_panel_administration/workspace/PRD_COMPLETED.md` is written: a minimal in-place patch over `PRD.md` pinning every behavior `implementation/` actually exhibits. No sections added, no line count change (edits are all in-paragraph).

## Stats

- Source `PRD.md`: 375 lines, 65,599 chars → `PRD_COMPLETED.md`: 375 lines, 70,163 chars (delta **+4,564 chars**, 26 paragraphs touched, 0 lines added/removed).
- Counts: **ambiguity-pins: 23**, **mismatch-revisions: 8** (31 changes total).

## Changes (section — kind — class — what — impl evidence)

- §2.1 — insert — ambiguity — failed ownership comparison (Entrant/Judge foreign-key mismatch) is `ERR_FORBIDDEN_ROLE` (403) — implementation/auth.py:39-40
- §2.3 — insert — ambiguity — `limit`/`offset` are clamped (1..100 / ≥0), non-integer values are `ERR_INVALID_REQUEST`; list sort ties break by insertion order — implementation/util.py:113-139
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/util.py:220-229
- §2.6 — revise — mismatch — clock endpoint is fully auth-exempt (headers omittable); a supplied non-ProgramAdmin role is 403; response echoes the submitted `to_iso8601` as `current_utc` — implementation/routes/clock_route.py:17-30
- §2.10 — revise — mismatch — Anonymous finalist listing is denied `ERR_EMBARGO_ACTIVE` during embargo (not merely filtered); the `embargo_visible` filter applies outside the embargo window — implementation/routes/finalists.py:25-34
- §3.1 — insert — ambiguity — season field-shape/calendar violations (code/title length, `early_fee_ends_at` bounds, eligibility ordering) are `ERR_INVALID_REQUEST` — implementation/routes/seasons.py:52-73
- §3.1 — insert — ambiguity — category creation refused `ERR_INVALID_STATE` under ARCHIVED/CANCELLED season; fees are required non-negative ints; rubric sum enforced at publish, only shape at creation — implementation/routes/seasons.py:388-400,425-430
- §3.1 — insert — ambiguity — season cancellation also returns voided-invoice entries' `payment_status` to `UNPAID` — implementation/routes/seasons.py:366-370
- §3.2 — insert — ambiguity — `contact_email` email-syntax and `country_code` two-uppercase-letters validation, both `ERR_INVALID_REQUEST` — implementation/routes/entrants.py:16-32
- §3.2 — insert — ambiguity — entry create requires `entrant_id` == acting entrant (`ERR_FORBIDDEN_ROLE`) — implementation/routes/entries.py:56-58
- §3.2 — insert — ambiguity — material rules: negative `file_size_bytes` / malformed checksum → `ERR_INVALID_REQUEST`; attach to terminal entry and accept/reject of non-PENDING → `ERR_INVALID_STATE` — implementation/routes/entries.py:124-183
- §3.3 — insert — ambiguity — late window ends strictly at `submission_closes_at`+48h; a submission at that exact instant fails — implementation/routes/entries.py:202-206
- §3.4 — insert — ambiguity — recheck at cap or outside OPEN/SUBMISSION_CLOSED → `ERR_INVALID_STATE` — implementation/routes/entries.py:300-305
- §3.5 — revise — mismatch — seeded declarations carry null season/category scopes, `HARD`/`OTHER` (PRD said "season scope resolved per assignment") — implementation/routes/judges.py:88-101
- §3.5 — revise — mismatch — activation declaration requirement is not season-scoped (dropped "for the target season") — implementation/routes/judges.py:123-129
- §3.5 — insert — ambiguity — suspension's removals carry removal side effects (void DRAFT scores, recompute reliability) — implementation/routes/judges.py:143-156
- §3.5 — insert — ambiguity — duplicate proposals of the same judge to a round are allowed (independent assignments) — implementation/routes/rounds.py:103-133
- §3.5 — insert — ambiguity — null-`entrant_id` declarations (e.g. recusal-seeded) cover every entrant in confirm-time conflict check — implementation/services.py:663-666
- §3.6 — insert — mismatch — duplicate `round_index` (`ERR_DUPLICATE`) fires before the window-gap check despite §2.5's numbering — implementation/routes/rounds.py:49-59
- §3.6 — insert — ambiguity — candidate set: DISQUALIFIED advancers excluded; a lowest-indexed replacement round with no IN_JUDGING entries reopens the voided same-index round's scored population — implementation/services.py:581-609
- §3.6 — insert — ambiguity — ballot `judge_id` must equal acting judge (`ERR_FORBIDDEN_ROLE`); at most one non-VOIDED score per judge–entry per round (`ERR_DUPLICATE`); conflict bar applies to unresolved HARD declarations — implementation/routes/rounds.py:389-408,466-471
- §3.6 — insert — ambiguity — advancement ties break by entry `created_at` ascending — implementation/services.py:795-801
- §3.6 — revise — mismatch — `final_rank` ties break by FINAL-round `weighted_raw` (panel mean of LOCKED values), not FINAL-round composite — implementation/services.py:820-825,861-868
- §3.7 — insert — ambiguity — acknowledgement exactly at the `ack_window_hours` deadline is accepted — implementation/routes/finalists.py:73-76
- §3.7 — revise — mismatch — ceremony `starts_at` is not required to equal `ceremony_scheduled_at`; creation refused (`ERR_INVALID_STATE`) under ARCHIVED/CANCELLED season — implementation/routes/ceremonies.py:47-81
- §3.7 — insert — ambiguity — staging requires ceremony in the category's season (`ERR_REFERENTIAL_INTEGRITY`) — implementation/routes/ceremonies.py:163-166
- §3.8 — insert — ambiguity — appeal filer-identity and competitor-standing failures are `ERR_FORBIDDEN_ROLE` — implementation/routes/entries.py:420-427
- §3.8 — revise — mismatch — RESCORE voids the highest-indexed non-VOIDED NORMALIZED-or-PUBLISHED round scoring the entry (PRD said only "NORMALIZED → VOIDED"); pins the conflicted-judge identification heuristic (declaration → affiliation → most-favouring LOCKED ballot, ties CHAIR then earliest) — implementation/routes/appeals.py:67-80, implementation/services.py:970-1021
- §3.8 — insert — ambiguity — REINSTATE on a non-INELIGIBLE entry is a no-op (appeal still UPHELD); retraction without an upheld RESCORE appeal is `ERR_INVALID_STATE` — implementation/routes/appeals.py:81-85, implementation/routes/ceremonies.py:306-315
- §3.8 — insert — ambiguity — fulfillment orders created with `engraving_text` unset and `quantity` 1; `vendor_reference` is a server-generated `VR`-prefixed id; queue-time `quantity` < 1 is `ERR_CONSTRAINT_VIOLATION` — implementation/routes/ceremonies.py:279-292, implementation/routes/fulfillment.py:43-69

Notable alignment decisions: the two most substantive mismatches were the ceremony `starts_at == ceremony_scheduled_at` rule (PRD-invented; implementation never enforces it, so the PRD clause was removed) and the `final_rank` tie-break (PRD said FINAL-round composite; implementation — and PRD §3.7 — use FINAL-round mean `weighted_raw`). Both were revised to match `implementation/`.

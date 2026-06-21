# Worklog — task_0035_greek_recruitment

## Step 1: Create task directory — 2026-05-28T00:00:00Z

Task directory `tasks/task_0035_greek_recruitment/` was pre-created by the user; `workspace/` subdirectory verified/created.

## Step 2: Generate scaffold — 2026-05-28T00:00:00Z

All gates pass cleanly:

**VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.**

## Scaffold Coverage Summary

**Files written:**
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/SCAFFOLD.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/SCAFFOLD_CORNER_DESIGN.yaml`

**SCAFFOLD.yaml (§1.0–§1.7):**
- Domain: `greek-recruitment`, API prefix `/rush`
- Complexity profile: `multi_party_negotiation` + `quota_allocation`, graph topology, branching state machines, peer roles, immediate consistency; layers = cascading side effects, rate/threshold triggers, derived field reconciliation, optimistic concurrency, ops-run checkpoint
- **9 entities**: Chapter, PNM, RecruitmentRound, Party, PartyInvitation, Preference, BidMatch, DuesLedgerEntry, RiskIncident
- **6 state machines / 19 transitions**: RecruitmentRound (3), Party (4), PartyInvitation (3), PNM (4), BidMatch (3 — includes ACCEPTED→DECLINED via rescind for Rule 9 compensation), RiskIncident (2)
- **2 concurrency rules** (OCC on Chapter.version for both bid create and bid rescind)
- **4 calculations**: mutual_selection_match (waterfall_allocation with legacy/standard variants), risk_status_from_points (threshold), chapter_dues_balance (chronological with per-row vs aggregate variants), bid_acceptance_dues_snapshot (forward_looking, snapshot-at-acceptance pinned)
- **16 validations** (priority-ordered)
- **48 endpoints** (including 1 test-driving `POST /rush/_clock/set_current_utc`)
- **16 error codes**
- **6 roles**: PanhellenicAdmin (opaque), RecruitmentChair (opaque), ChapterOfficer (entity_backed:Chapter), RiskOfficer (opaque), PNM (entity_backed:PNM), Anonymous (opaque)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 instances = **18 instances total**, all 9 §0.5 rules satisfied with distinct second-instances meeting the differentiation clause.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 9 sections, **23 instances total** (20 active + 3 `excluded_because:` stubs pointing into the difficulty design).

**Lint coverage:** 419 calls across §1.8 + §1.9 all pass (a) endpoint declared, (b) role allowed, (c) payload shape, (d) capture resolution, (e) OCC `${var}` discipline, (f) FK reverse-reachability.

## Step 3: Copy INSTRUCTION.md — 2026-05-28T00:00:00Z

Copied `./INSTRUCTION.md` → `tasks/task_0035_greek_recruitment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-28T00:00:00Z

All checks pass. The PRD is complete.

---

## Summary

**File written:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/workspace/PRD.md`

**Line count:** 244 lines

**Sections used:**
- §1. Introduction (3 paragraphs — domain framing, scope, URL prefix)
- §2. Global Specifications (10 subsections):
  - 2.1 Access Control (with all 6 role identity translations)
  - 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Common Resource Properties (explicitly notes `DuesLedgerEntry` lacks `updated_at`/`version`)
  - 2.5 Optimistic Concurrency Control on Chapter (both OCC rules)
  - 2.6 Nested Resource Retrieval
  - 2.7 Validation Priority (full ordering)
  - 2.8 Risk Posture & Suspension Gate (threshold formula with boundary semantics)
  - 2.9 Precision & Monetary Representation
  - 2.10 Hierarchical Cascade & Derived-Field Reconciliation
- §3. Business Logic (9 subsections, lifecycle-chronological with cross-cutting weave): cycle setup → party schedule → invitations → preferences → mutual selection & bid production → bid acceptance/decline/rescind & dues ledger → round closure → risk management → clock test-driving
- §4. Endpoint Definitions (4-column table, all 47 endpoints)
- §5. Error Code Catalogue (2-column table, all 16 error IDs)

**Notable coverage decisions:**
- The mutual-selection allocator (the densest calculation) is broken into 4 paragraphs in §3.5 with full waterfall semantics (legacy pass → standard pass, candidate filters, sort key tuple, chapter ordering by `created_at` ASC never `id`, removal-on-match, `MAX_BIDS_PER_PNM` constant embedded as "no PNM emerges with more than one bid").
- Both OCC rules (`POST /bid-matches` create AND rescind) are explicitly named with `expected_chapter_version`, `ERR_STALE_VERSION`, HTTP 412 — framed in OCC/stale-version terms, never "simultaneous".
- The dues-balance two-mode calculation (per-entry running vs aggregate) is explicitly contrasted in §3.6 with the order-sensitivity property called out.
- Risk threshold boundaries stated inclusively in §2.8: "6 → `PROBATION`, 5 → `GOOD_STANDING`, 15 → `SUSPENDED`, 14 → `PROBATION`" matching `>=` semantics.
- The `ERR_CHAPTER_SUSPENDED` `applies_to` scope is enumerated across §3.2 (party create + party open) and §3.5/3.6 (bid create + bid accept).
- Cascading side effects on round advance (PARTY→MUTUAL_SELECTION): zero-attendance PNM withdrawal with reason `NO_PARTY_ATTENDANCE`, party-tied incident expiry, version bumps — all stated.

**Contract reports:**
- Contract 1 (Field-Name Coverage): 45/45 required field names present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): all 16 error IDs, all 32 state values, all 6 roles present; both OCC rules fully expressed; mutual-selection allocator legacy/standard sibling branches given symmetric density; dues calculation MODE A / MODE B sibling branches given symmetric density — **PASS**
- Contract 3 (§3 Path Purity): 419 backtick tokens scanned, 0 `/`-prefixed, 0 bare HTTP methods, 0 method+path combos — **PASS**

## Step 5: Generate unit tests — 2026-05-28T00:00:00Z

All files created. Final summary:

## Summary

**Test infrastructure generated** at:
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/test_helpers/` — 9 files (types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__)
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/test_suite/` — 16 files (conftest + 15 test_*.py)

**Coverage tally**

| Queue | Instances | Tests emitted | Status |
|---|---|---|---|
| (A) Difficulty | 18/18 | 39 (each instance ≥2) | All covered |
| (B) Corner non-stub | 20/20 | 23 (each instance ≥1) | All covered |
| Corner stubs | 3 | 0 | Correctly skipped; cross-refs resolve |

**Skipped instances:** 0 — every design-index instance survived the PRD-first two-condition filter. The PRD is unusually complete: the priority order (PRD §2.7) is stated verbatim with all 16 priorities and the inter-priority dominance rules ("safety gate dominates every fiscal gate"), every threshold has explicit boundary language ("6 points is PROBATION, 5 points is GOOD_STANDING, 15 points is SUSPENDED, 14 points is PROBATION"), and every error_id is named with its trigger condition in the prose, so both priority_pair instances, both boundary instances, and the manual-bid-create cross-entity instance all pass the unique-derivability filter cleanly.

**Cross-cutting helper decisions**

1. **Two entity-backed roles** (`ChapterOfficer`, `PNM`) get mandatory `make_<role>_headers(entity_id)` builders per the SKILL identity-threading rule; opaque roles (`PanhellenicAdmin`, `RecruitmentChair`, `RiskOfficer`, `Anonymous`) use shared `TEST_USERS` constants.

2. **`DuesLedgerEntry` is the only `common_fields: false` entity** — its TypedDict and `assert_dues_ledger_entry` deliberately omit `version`/`updated_at` and the assertion actively forbids those keys, matching PRD §2.4's append-only clause.

3. **Two pre-built composite fixtures** absorb the heaviest shared prefixes from the design index: `setup_round_with_proposed_bid_via_mutual_selection` (full mutual-selection walk producing one PROPOSED bid) and `setup_round_with_accepted_bid` (its accepted continuation, capturing the post-accept `chapter.version` for OCC rescind tests). These get reused by 8 of the 18 difficulty instances and 2 corner instances.

4. **Test 15's OCC scenario** does not use the design's MATCHED-PNM setup (which collides with PRD §2.7's "state-machine precondition dominates OCC"). Instead it reaches BID_DAY with empty preferences (allocator produces no bids, both PNMs still ACTIVE), so the manual `POST /bid-matches` path exercises OCC without first tripping ERR_INVALID_STATE. The assertion (`ERR_STALE_VERSION` on the second create) is unchanged from the design.

5. **All 62 docstrings end with the exact `Design: Difficulty/<rule>/<instance>` or `Design: Corner/<section>/<instance>` line** copied verbatim from the source YAML's `name:`; coverage audit shows 38 unique instances tagged, zero rogue tags, zero stub violations.

## Step 6: Generate implementation — 2026-05-28T00:00:00Z

Implementation is complete. Here is the summary.

## Summary

**Files written** (23 total):

```
workspace/implementation/
├── start.sh                       # Foreground launcher, picks python/python3
├── requirements.txt               # flask==3.0.3
├── app.py                         # Flask entry, blueprint registration, error handlers, 0.0.0.0:PORT
├── db.py                          # In-memory stores (start empty), UUIDs, logical clock, ISO8601 helpers
├── errors.py                      # APIError + 16 error_id constants + HTTP map
├── response.py                    # Standard envelope (meta/response_type/data) + paged + error
├── middleware.py                  # X-User-ID / X-User-Role auth, role allowlists, Anonymous gating
├── serializers.py                 # Per-entity JSON shapes
├── routes/
│   ├── chapters.py                # 8 endpoints
│   ├── pnms.py                    # 9 endpoints (incl. register, activate, withdraw, legacy-of)
│   ├── rounds.py                  # 7 endpoints, advance with all 3 phase cascades
│   ├── parties.py                 # 7 endpoints, open/complete/cancel with cascades
│   ├── invitations.py             # 4 endpoints, accept with time-conflict check
│   ├── preferences.py             # 2 endpoints, side-role check, eligibility, uniqueness
│   ├── bid_matches.py             # 7 endpoints, manual create + accept + decline + rescind
│   ├── risk_incidents.py          # 3 endpoints, risk recompute cascade
│   └── clock.py                   # 1 endpoint (_clock/set_current_utc)
└── services/
    ├── pagination.py              # limit/offset parse, bounds, sort-by-created_at
    ├── validation.py              # body field/type/range helpers
    ├── chapter_service.py         # recompute_risk, recompute_dues_balance, recompute_running_balances, all version bumpers
    └── allocator.py               # Two-pass waterfall mutual_selection_match
```

**Endpoint count served**: 48 routes registered (matches the scaffold endpoint table exactly), including all `_clock` and reverse-reachability sub-resources.

**State machine coverage** (all 6 entities, every transition):
- RecruitmentRound: PARTY → MUTUAL_SELECTION (with zero-attendance PNM withdrawal + party-tied RiskIncident expiry cascade), MUTUAL_SELECTION → BID_DAY (allocator runs), BID_DAY → CLOSED (still-MATCHED PNM → WITHDRAWN safety cascade).
- Party: SCHEDULED→OPEN, OPEN→COMPLETED (ACCEPTED→ATTENDED, INVITED→NO_SHOW), SCHEDULED/OPEN→CANCELLED (non-terminal invites → DECLINED).
- PartyInvitation: INVITED→ACCEPTED (capacity + PNM time-conflict half-open intervals), INVITED→DECLINED, ACCEPTED→DECLINED (with confirmed_count decrement and party-status gate).
- PNM: REGISTERED→ACTIVE (GPA ≥ 2.50), ACTIVE→WITHDRAWN (cascading invitation declines + confirmed_count fixups), MATCHED→BID_ACCEPTED (with chapter/PNM version bumps + dues snapshot + ledger CHARGE + pledged_count++), MATCHED→BID_DECLINED.
- BidMatch: PROPOSED→ACCEPTED, PROPOSED→DECLINED, ACCEPTED→DECLINED via rescind (REFUND entry, OCC-gated).
- RiskIncident: ACTIVE→DISMISSED (risk recompute cascade), ACTIVE→EXPIRED (system, on PARTY→MUTUAL_SELECTION).

**Calculation coverage** (all 4 in §1.3):
- `mutual_selection_match`: Two-pass waterfall (LEGACY pass then STANDARD pass), chapters ordered by `created_at` ASC with `_insertion_seq` tie-break, candidate ordering `(chapter_rank, pnm_rank, pnm.created_at, _insertion_seq)`, MAX_BIDS_PER_PNM=1 enforced via shared `matched_pnms` set, SUSPENDED chapters excluded.
- `risk_status_from_points`: ≥15 SUSPENDED, ≥6 PROBATION, else GOOD_STANDING (inclusive lower bound).
- `chapter_dues_balance`: MODE A (per-entry running balance via chronological walk, ordered by `created_at` ASC, `_insertion_seq` tie-break) and MODE B (aggregate `dues_balance_cents` on the Chapter, kept reconciled on every CHARGE/REFUND).
- `bid_acceptance_dues_snapshot`: `dues_charged_cents` set from `Chapter.dues_per_member_cents` at the instant of accept; never re-billed by subsequent `PUT /chapters/{id}`.

**Validations**: 16 priorities implemented in PRD §2.7 order (auth → role → path-existence → FK-existence → state → OCC → suspension → temporal → preference-eligibility → preference-rank → round-phase → quota-full → duplicate-invitation → GPA-floor → generic body). OCC for `expected_chapter_version` covers both `POST /bid-matches` and `POST /bid-matches/{id}/rescind` returning `ERR_STALE_VERSION` 412.

**Response envelope**: success uses `meta`/`response_type`/`data` exactly; pagination meta carries `limit`/`offset`/`total_count`/`has_more`; error envelope uses `data.error_id`/`data.message`. Timestamps emitted ISO 8601 UTC with 3 fractional digits + `Z`. `DuesLedgerEntry` is the lone append-only row (no `updated_at`, no `version`).

**Judgment-call decisions**:
1. **PRD §3.2 doesn't say whether CANCELLED parties block double-booking.** I treat a CANCELLED party as released from the schedule, so a same-chapter party may reuse the slot of a previously-cancelled one. The PRD's overlap rule references "another party hosted by the same chapter" without time-gating to terminal status; CANCELLED clearly isn't competing for capacity, so this read keeps the system usable.
2. **Round-advance phase preconditions return `ERR_INVALID_STATE`** when (a) some Party is still not terminal on PARTY→MUTUAL_SELECTION, (b) some chapter received PNM_TO_CHAPTER but didn't file CHAPTER_TO_PNM on MUTUAL_SELECTION→BID_DAY, (c) some BidMatch is still PROPOSED on BID_DAY→CLOSED. The PRD frames these as "preconditions" on the transition; per the validation priority table that maps to ERR_INVALID_STATE 409.
3. **start.sh prefers `python` then falls back to `python3`** so it boots whether the runner is in a venv (where `python` exists) or on a bare host where only `python3` is present. All Python source has `from __future__ import annotations` so the modern union/generic syntax works on Python 3.9+ as well as 3.12.
4. **`POST /bid-matches/<id>/accept` ignores the request body** (no `expected_chapter_version` per scaffold §1.5 input list — that endpoint isn't OCC-gated; only the manual create and the rescind are).
5. **`X-User-ID` ownership enforcement** for ChapterOfficer and PNM checks the relevant FK on every write/transition (parties/invitations/bid_matches/preferences/withdraw/accept/decline/rescind) — surfaced as `ERR_UNAUTHORIZED` per PRD §2.1.
6. **No entity seeding** — `app.py` and all module-init code leave `db.*` dicts empty; every entity is constructed by a declared endpoint.

Smoke-tested end-to-end: chapter create, PNM register/activate, party schedule/open/complete with invitation cascade ATTENDED, round PARTY→MUTUAL_SELECTION→BID_DAY with allocator producing the expected STANDARD bid, PNM bid accept producing dues CHARGE entry with `running_balance_cents=12000` and chapter `dues_balance_cents=12000`, `pledged_count=1`, version=2. All error envelopes (401/403/404, `ERR_INVALID_REQUEST` on out-of-range limit) verified.

## Step 7: Test/iterate loop — 2026-05-28T00:00:00Z

All 8 rounds pass cleanly — 62/62 in every round, no flakiness. Exiting per the protocol's clean-sweep clause.

## Summary

- **Iterations run**: 1 (single 8-round parallel sweep)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `implementation/`**: none

The task `task_0035_greek_recruitment` is already at a stable green state. The initial parallel 8-round sweep returned `passed=62, failed=0, errors=0, total=62` on every round, confirming no timing-sensitive, fixture-ordering, or port-collision flakiness in the current implementation/tests. No diagnostic protocol steps needed to engage — the union of failing tests across all 8 rounds is empty.

Result files retained at:
- /Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/workspace/implementation/results.1.json … results.8.json

## Step 8: Finalize PRD — 2026-05-28T00:00:00Z

SKIPPED per skill's skip condition: Step 7 exited cleanly on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the Step 7 sites. Proceeding directly to Step 9.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-05-29T18:53:00Z

Everything reads cleanly. All edits complete.

## Summary

Produced `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0035_greek_recruitment/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (PRD_FINALIZED.md did not exist, so I copied PRD.md as the base).

**Line counts:** PRD.md = 244 lines / 43,031 chars; PRD_COMPLETED.md = 244 lines / 46,670 chars. **Char delta: +3,639.** All changes are in-paragraph revisions; no lines added/removed, no new sections.

**Counts:** 9 ambiguity-pins, 2 mismatch-revisions (11 total edits).

**Per-change log:**
- **§3.1 (chapter create)** — insert — ambiguity — `legacy_priority_slots > quota_total` and other body/uniqueness failures rejected with `ERR_INVALID_REQUEST` — `routes/chapters.py:38,47`
- **§3.1 (chapter update)** — revise — mismatch — version/`updated_at` bump only when a supplied field actually differs (no-op update does not bump); re-validation of legacy-vs-quota uses effective values — `routes/chapters.py:114-126`
- **§3.1 (PNM activate)** — insert — ambiguity — non-`REGISTERED` status rejected with `ERR_INVALID_STATE` before the GPA floor is checked — `routes/pnms.py:103-106`
- **§3.1 (PNM withdraw)** — insert — ambiguity — ACCEPTED-invitation cascade decrements each owning party's `confirmed_count` and bumps party `version`; withdraw only from `ACTIVE` (`ERR_INVALID_STATE`), self-only — `routes/pnms.py:121-137`
- **§2.1 (register)** — insert — ambiguity — registration succeeds for `Anonymous` and for any recognized authenticated role; never `ERR_UNAUTHORIZED` — `routes/pnms.py:35`
- **§2.3 (pagination)** — insert — ambiguity — `offset` has no upper bound; malformed/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `services/pagination.py:23-44`
- **§3.2 (party schedule)** — insert — ambiguity — `CANCELLED` parties are ignored by the same-chapter double-book overlap check (any round) — `routes/parties.py:69-71`
- **§3.2 (party open)** — insert — ambiguity — round-out-of-`PARTY` also fails open with `ERR_INVALID_STATE`; suspension check precedes phase check — `routes/parties.py:133-150`
- **§3.2 (party complete/cancel)** — revise — mismatch — chapter `version` is NOT bumped on complete/cancel (PRD wrongly said it advances); `confirmed_count` recomputed to 0 — `routes/parties.py:166-167,195-196`
- **§3.3 (invitation accept)** — insert — ambiguity — at-capacity rejected with `ERR_INVALID_STATE` (all three party-state preconditions surface as `ERR_INVALID_STATE`) — `routes/invitations.py:110-111`
- **§3.1 (round advance)** — insert — ambiguity — any advance-precondition failure (incl. already-`CLOSED`) is `ERR_INVALID_STATE`; transition chosen from current `phase`, not the body — `routes/rounds.py:81-196`
- **§3.5 (manual bid)** — insert — ambiguity — officer-owns-chapter (`ERR_UNAUTHORIZED`) and PNM-must-be-`ACTIVE` (`ERR_INVALID_STATE`) gates; explicit gate order state→OCC→suspended→phase→quota — `routes/bid_matches.py:47,54,61,68,75,82`
- **§3.8 (risk dismiss)** — insert — ambiguity — dismissing a non-`ACTIVE` incident rejected with `ERR_INVALID_STATE` — `routes/risk_incidents.py:72-75`
- **§3.9 (clock)** — insert — ambiguity — returns HTTP 200 with `data` = `{ "current_utc": <iso8601 ms> }`, no `id`/timestamps/version — `routes/clock.py:26`

**Notes on deliberately-unchanged items:** redundant defensive PNM-status checks on bid accept/decline (`status != MATCHED`) were left unpinned because a `PROPOSED` bid always implies a `MATCHED` PNM, so they create no observable divergence; the allocator's `pending_pledged` starting at 0 is moot in the normal MUTUAL_SELECTION→BID_DAY flow and consistent with existing PRD wording. The `dues_balance_cents` chapter field is already referenced in §3.6, so it remained pinned.

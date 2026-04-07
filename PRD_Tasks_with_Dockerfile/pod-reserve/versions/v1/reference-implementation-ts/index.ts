import express, { Request, Response, NextFunction } from 'express';

type PodcastPosture = 'NORMAL' | 'RESTRICTED';
type EpisodeStatus = 'DRAFT' | 'SUBMITTED' | 'LIVE' | 'RETRACTED';
type EpisodeClearance = 'CLEAR' | 'UNDER_REVIEW';
type ContentRating = 'GENERAL' | 'MATURE';
type DealStatus = 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'CLOSED';
type BrandTier = 'FAMILY_SAFE' | 'STANDARD';
type ReservationStatus = 'HOLD' | 'APPROVED' | 'NEEDS_REVIEW' | 'OVERBOOKED' | 'SETTLED' | 'CREDITED' | 'CANCELED' | 'EXPIRED';
type Placement = 'PRE_ROLL' | 'MID_ROLL' | 'POST_ROLL';
type ClaimKind = 'RIGHTS' | 'BRAND_SAFETY';
type ClaimStatus = 'OPEN' | 'CLOSED';
type ClaimOutcome = 'ACCEPTED' | 'REJECTED' | 'WITHDRAWN';

interface Podcast {
  id: string;
  name: string;
  ad_capacity_seconds: number;
  ops_run_index: number;
  version: number;
  had_accepted_claim: boolean;
}

interface Episode {
  id: string;
  podcast_id: string;
  title: string;
  content_rating: ContentRating;
  status: EpisodeStatus;
  ad_slots_total_seconds: number;
  version: number;
}

interface Deal {
  id: string;
  podcast_id: string;
  advertiser_name: string;
  brand_tier: BrandTier;
  budget_total_cents: number;
  slot_price_cents: number;
  script_text: string;
  script_version: number;
  status: DealStatus;
  version: number;
}

interface Reservation {
  id: string;
  podcast_id: string;
  episode_id: string;
  deal_id: string;
  placement: Placement;
  slot_seconds: number;
  status: ReservationStatus;
  script_version_pinned: number | null;
  version: number;
  ops_run_at_creation: number;
}

interface Claim {
  id: string;
  podcast_id: string;
  episode_id: string;
  kind: ClaimKind;
  status: ClaimStatus;
  outcome: ClaimOutcome | null;
  version: number;
}

const podcasts: Map<string, Podcast> = new Map();
const episodes: Map<string, Episode> = new Map();
const deals: Map<string, Deal> = new Map();
const reservations: Map<string, Reservation> = new Map();
const claims: Map<string, Claim> = new Map();

let idCounter = 1;
function generateId(): string {
  return String(idCounter++);
}

function successResponse(data: any, isArray = false): object {
  return {
    response_type: isArray ? 'array' : 'object',
    data
  };
}

function errorResponse(error_code: string, message: string, extra?: Record<string, any>): object {
  return {
    response_type: 'error',
    data: { error_code, message, ...(extra ?? {}) }
  };
}

function getReservationsForPodcast(podcastId: string): Reservation[] {
  return Array.from(reservations.values()).filter(r => r.podcast_id === podcastId);
}

function getReservationsForEpisode(episodeId: string): Reservation[] {
  return Array.from(reservations.values()).filter(r => r.episode_id === episodeId);
}

function getReservationsForDeal(dealId: string): Reservation[] {
  return Array.from(reservations.values()).filter(r => r.deal_id === dealId);
}

function getClaimsForPodcast(podcastId: string): Claim[] {
  return Array.from(claims.values()).filter(c => c.podcast_id === podcastId);
}

function getClaimsForEpisode(episodeId: string): Claim[] {
  return Array.from(claims.values()).filter(c => c.episode_id === episodeId);
}

function getOpenClaimCount(podcastId: string): number {
  return getClaimsForPodcast(podcastId).filter(c => c.status === 'OPEN').length;
}

function hasAcceptedClaim(podcastId: string): boolean {
  return getClaimsForPodcast(podcastId).some(c => c.outcome === 'ACCEPTED');
}

function getPodcastPosture(podcast: Podcast): PodcastPosture {
  const openCount = getOpenClaimCount(podcast.id);
  if (openCount >= 2) return 'RESTRICTED';
  if (podcast.had_accepted_claim) return 'RESTRICTED';
  return 'NORMAL';
}

function getEpisodeClearance(episodeId: string): EpisodeClearance {
  const openClaims = getClaimsForEpisode(episodeId).filter(c => c.status === 'OPEN');
  return openClaims.length > 0 ? 'UNDER_REVIEW' : 'CLEAR';
}

function getPodcastAdHeldSeconds(podcastId: string): number {
  return getReservationsForPodcast(podcastId)
    .filter(r => r.status === 'HOLD')
    .reduce((sum, r) => sum + r.slot_seconds, 0);
}

function getPodcastAdCommittedSeconds(podcastId: string): number {
  return getReservationsForPodcast(podcastId)
    .filter(r => ['APPROVED', 'NEEDS_REVIEW', 'SETTLED'].includes(r.status))
    .reduce((sum, r) => sum + r.slot_seconds, 0);
}

function getEpisodeAdHeldSeconds(episodeId: string): number {
  return getReservationsForEpisode(episodeId)
    .filter(r => r.status === 'HOLD')
    .reduce((sum, r) => sum + r.slot_seconds, 0);
}

function getEpisodeAdCommittedSeconds(episodeId: string): number {
  return getReservationsForEpisode(episodeId)
    .filter(r => ['APPROVED', 'NEEDS_REVIEW', 'SETTLED'].includes(r.status))
    .reduce((sum, r) => sum + r.slot_seconds, 0);
}

function getDealBudgetHeldCents(dealId: string): number {
  const deal = deals.get(dealId);
  if (!deal) return 0;
  return getReservationsForDeal(dealId)
    .filter(r => r.status === 'HOLD')
    .length * deal.slot_price_cents;
}

function getDealBudgetCommittedCents(dealId: string): number {
  const deal = deals.get(dealId);
  if (!deal) return 0;
  return getReservationsForDeal(dealId)
    .filter(r => ['APPROVED', 'NEEDS_REVIEW'].includes(r.status))
    .length * deal.slot_price_cents;
}

function getDealBudgetSpentCents(dealId: string): number {
  const deal = deals.get(dealId);
  if (!deal) return 0;
  return getReservationsForDeal(dealId)
    .filter(r => r.status === 'SETTLED')
    .length * deal.slot_price_cents;
}

function isTerminalReservationStatus(status: ReservationStatus): boolean {
  return ['SETTLED', 'CREDITED', 'CANCELED', 'EXPIRED'].includes(status);
}

function retractEpisode(episode: Episode): void {
  episode.status = 'RETRACTED';
  episode.version++;

  const episodeReservations = getReservationsForEpisode(episode.id);
  for (const reservation of episodeReservations) {
    if (reservation.status === 'HOLD') {
      reservation.status = 'CANCELED';
      reservation.version++;
    } else if (reservation.status === 'APPROVED' || reservation.status === 'NEEDS_REVIEW') {
      reservation.status = 'CANCELED';
      reservation.version++;
    } else if (reservation.status === 'SETTLED') {
      reservation.status = 'CREDITED';
      reservation.version++;
    }

    else if (reservation.status === 'OVERBOOKED') {
      reservation.status = 'CANCELED';
      reservation.version++;
    }
  }
}

function handleEpisodeCapacityReduction(episode: Episode): void {
  const episodeReservations = getReservationsForEpisode(episode.id);

  let heldSeconds = 0;
  let committedSeconds = 0;

  const holdReservations = episodeReservations
    .filter(r => r.status === 'HOLD')
    .sort((a, b) => parseInt(b.id) - parseInt(a.id));

  const approvedReservations = episodeReservations
    .filter(r => ['APPROVED', 'NEEDS_REVIEW'].includes(r.status))
    .sort((a, b) => parseInt(b.id) - parseInt(a.id));

  for (const r of holdReservations) heldSeconds += r.slot_seconds;
  for (const r of approvedReservations) committedSeconds += r.slot_seconds;

  const totalUsed = heldSeconds + committedSeconds;

  if (totalUsed <= episode.ad_slots_total_seconds) {
    return;
  }

  let excessSeconds = totalUsed - episode.ad_slots_total_seconds;

  for (const reservation of holdReservations) {
    if (excessSeconds <= 0) break;
    reservation.status = 'CANCELED';
    reservation.version++;
    excessSeconds -= reservation.slot_seconds;
  }

  for (const reservation of approvedReservations) {
    if (excessSeconds <= 0) break;
    reservation.status = 'OVERBOOKED';
    reservation.version++;
    excessSeconds -= reservation.slot_seconds;
  }
}

function checkBrandSafety(deal: Deal, episode: Episode): boolean {
  if (deal.brand_tier === 'FAMILY_SAFE' && episode.content_rating === 'MATURE') {
    return false;
  }
  return true;
}

const app = express();
app.use(express.json());

app.post('/podcasts', (req: Request, res: Response) => {
  const { name, ad_capacity_seconds } = req.body;

  if (!name || ad_capacity_seconds === undefined) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required fields: name, ad_capacity_seconds'));
  }

  if (typeof ad_capacity_seconds !== 'number' || ad_capacity_seconds < 0) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'ad_capacity_seconds must be a non-negative number'));
  }

  const podcast: Podcast = {
    id: generateId(),
    name,
    ad_capacity_seconds,
    ops_run_index: 0,
    version: 1,
    had_accepted_claim: false
  };

  podcasts.set(podcast.id, podcast);

  const adHeld = getPodcastAdHeldSeconds(podcast.id);
  const adCommitted = getPodcastAdCommittedSeconds(podcast.id);

  return res.status(201).json(successResponse({
    id: podcast.id,
    name: podcast.name,
    ad_capacity_seconds: podcast.ad_capacity_seconds,
    posture: getPodcastPosture(podcast),
    open_claim_count: getOpenClaimCount(podcast.id),
    ops_run_index: podcast.ops_run_index,
    ad_held_seconds: adHeld,
    ad_committed_seconds: adCommitted,
    ad_available_seconds: Math.max(0, podcast.ad_capacity_seconds - adHeld - adCommitted),
    version: podcast.version
  }));
});

app.get('/podcasts/:podcast_id', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const adHeld = getPodcastAdHeldSeconds(podcast.id);
  const adCommitted = getPodcastAdCommittedSeconds(podcast.id);

  return res.status(200).json(successResponse({
    id: podcast.id,
    name: podcast.name,
    ad_capacity_seconds: podcast.ad_capacity_seconds,
    posture: getPodcastPosture(podcast),
    open_claim_count: getOpenClaimCount(podcast.id),
    ops_run_index: podcast.ops_run_index,
    ad_held_seconds: adHeld,
    ad_committed_seconds: adCommitted,
    ad_available_seconds: Math.max(0, podcast.ad_capacity_seconds - adHeld - adCommitted),
    version: podcast.version
  }));
});

app.post('/podcasts/:podcast_id/run_ops', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  if (String(podcast.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  podcast.ops_run_index++;
  podcast.version++;

  const podcastReservations = getReservationsForPodcast(podcast.id);
  for (const reservation of podcastReservations) {
    if (reservation.status === 'HOLD') {

      if (podcast.ops_run_index - reservation.ops_run_at_creation >= 2) {
        reservation.status = 'EXPIRED';
        reservation.version++;
      }
    }
  }

  const openCount = getOpenClaimCount(podcast.id);
  if (openCount === 0 && podcast.had_accepted_claim) {
    podcast.had_accepted_claim = false;
  }

  const adHeld = getPodcastAdHeldSeconds(podcast.id);
  const adCommitted = getPodcastAdCommittedSeconds(podcast.id);

  return res.status(200).json(successResponse({
    id: podcast.id,
    name: podcast.name,
    ad_capacity_seconds: podcast.ad_capacity_seconds,
    posture: getPodcastPosture(podcast),
    open_claim_count: openCount,
    ops_run_index: podcast.ops_run_index,
    ad_held_seconds: adHeld,
    ad_committed_seconds: adCommitted,
    ad_available_seconds: Math.max(0, podcast.ad_capacity_seconds - adHeld - adCommitted),
    version: podcast.version
  }));
});

app.post('/podcasts/:podcast_id/episodes', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const { title, content_rating, ad_slots_total_seconds } = req.body;

  if (!title || !content_rating || ad_slots_total_seconds === undefined) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required fields: title, content_rating, ad_slots_total_seconds'));
  }

  if (!['GENERAL', 'MATURE'].includes(content_rating)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'content_rating must be GENERAL or MATURE'));
  }

  if (typeof ad_slots_total_seconds !== 'number' || ad_slots_total_seconds < 0) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'ad_slots_total_seconds must be a non-negative number'));
  }

  const episode: Episode = {
    id: generateId(),
    podcast_id: podcast.id,
    title,
    content_rating,
    status: 'DRAFT',
    ad_slots_total_seconds,
    version: 1
  };

  episodes.set(episode.id, episode);

  return res.status(201).json(successResponse({
    id: episode.id,
    podcast_id: episode.podcast_id,
    title: episode.title,
    content_rating: episode.content_rating,
    status: episode.status,
    clearance: getEpisodeClearance(episode.id),
    ad_slots_total_seconds: episode.ad_slots_total_seconds,
    ad_slots_held_seconds: 0,
    ad_slots_committed_seconds: 0,
    reservations: [],
    version: episode.version
  }));
});

app.get('/podcasts/:podcast_id/episodes/:episode_id', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const episode = episodes.get(req.params.episode_id);

  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  const episodeReservations = getReservationsForEpisode(episode.id)
    .filter(r => !['CANCELED', 'EXPIRED'].includes(r.status) || ['SETTLED', 'CREDITED'].includes(r.status))
    .map(r => ({
      id: r.id,
      deal_id: r.deal_id,
      placement: r.placement,
      slot_seconds: r.slot_seconds,
      status: r.status,
      script_version_pinned: r.script_version_pinned,
      version: r.version
    }));

  const allReservations = getReservationsForEpisode(episode.id).map(r => ({
    id: r.id,
    deal_id: r.deal_id,
    placement: r.placement,
    slot_seconds: r.slot_seconds,
    status: r.status,
    script_version_pinned: r.script_version_pinned,
    version: r.version
  }));

  return res.status(200).json(successResponse({
    id: episode.id,
    podcast_id: episode.podcast_id,
    title: episode.title,
    content_rating: episode.content_rating,
    status: episode.status,
    clearance: getEpisodeClearance(episode.id),
    ad_slots_total_seconds: episode.ad_slots_total_seconds,
    ad_slots_held_seconds: getEpisodeAdHeldSeconds(episode.id),
    ad_slots_committed_seconds: getEpisodeAdCommittedSeconds(episode.id),
    reservations: allReservations,
    version: episode.version
  }));
});

app.put('/podcasts/:podcast_id/episodes/:episode_id', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const episode = episodes.get(req.params.episode_id);

  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  if (String(episode.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (episode.status !== 'DRAFT') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Episode can only be edited in DRAFT status'));
  }

  const { title, content_rating, ad_slots_total_seconds } = req.body;

  const oldContentRating = episode.content_rating;

  if (title !== undefined) episode.title = title;
  if (content_rating !== undefined) {
    if (!['GENERAL', 'MATURE'].includes(content_rating)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'content_rating must be GENERAL or MATURE'));
    }
    episode.content_rating = content_rating;
  }
  if (ad_slots_total_seconds !== undefined) {
    if (typeof ad_slots_total_seconds !== 'number' || ad_slots_total_seconds < 0) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'ad_slots_total_seconds must be a non-negative number'));
    }
    episode.ad_slots_total_seconds = ad_slots_total_seconds;
  }

  episode.version++;

  handleEpisodeCapacityReduction(episode);

  if (content_rating !== undefined && content_rating !== oldContentRating) {
    const episodeReservations = getReservationsForEpisode(episode.id);
    for (const reservation of episodeReservations) {
      if (reservation.status === 'APPROVED') {
        const deal = deals.get(reservation.deal_id);
        if (deal && !checkBrandSafety(deal, episode)) {
          reservation.status = 'NEEDS_REVIEW';
          reservation.version++;
        }
      }
    }
  }

  const allReservations = getReservationsForEpisode(episode.id).map(r => ({
    id: r.id,
    deal_id: r.deal_id,
    placement: r.placement,
    slot_seconds: r.slot_seconds,
    status: r.status,
    script_version_pinned: r.script_version_pinned,
    version: r.version
  }));

  return res.status(200).json(successResponse({
    id: episode.id,
    podcast_id: episode.podcast_id,
    title: episode.title,
    content_rating: episode.content_rating,
    status: episode.status,
    clearance: getEpisodeClearance(episode.id),
    ad_slots_total_seconds: episode.ad_slots_total_seconds,
    ad_slots_held_seconds: getEpisodeAdHeldSeconds(episode.id),
    ad_slots_committed_seconds: getEpisodeAdCommittedSeconds(episode.id),
    reservations: allReservations,
    version: episode.version
  }));
});

app.post('/podcasts/:podcast_id/episodes/:episode_id/submit', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const episode = episodes.get(req.params.episode_id);

  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  if (String(episode.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (episode.status !== 'DRAFT') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Episode can only be submitted from DRAFT status'));
  }

  episode.status = 'SUBMITTED';
  episode.version++;

  const allReservations = getReservationsForEpisode(episode.id).map(r => ({
    id: r.id,
    deal_id: r.deal_id,
    placement: r.placement,
    slot_seconds: r.slot_seconds,
    status: r.status,
    script_version_pinned: r.script_version_pinned,
    version: r.version
  }));

  return res.status(200).json(successResponse({
    id: episode.id,
    podcast_id: episode.podcast_id,
    title: episode.title,
    content_rating: episode.content_rating,
    status: episode.status,
    clearance: getEpisodeClearance(episode.id),
    ad_slots_total_seconds: episode.ad_slots_total_seconds,
    ad_slots_held_seconds: getEpisodeAdHeldSeconds(episode.id),
    ad_slots_committed_seconds: getEpisodeAdCommittedSeconds(episode.id),
    reservations: allReservations,
    version: episode.version
  }));
});

app.post('/podcasts/:podcast_id/episodes/:episode_id/publish', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  if (getPodcastPosture(podcast) === 'RESTRICTED') {
    return res.status(403).json(errorResponse('ERR_PODCAST_RESTRICTED', 'Cannot publish while podcast is restricted'));
  }

  const episode = episodes.get(req.params.episode_id);

  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  if (String(episode.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (episode.status !== 'SUBMITTED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Episode can only be published from SUBMITTED status'));
  }

  if (getEpisodeClearance(episode.id) === 'UNDER_REVIEW') {
    return res.status(409).json(errorResponse('ERR_EPISODE_UNDER_REVIEW', 'Cannot publish episode that is under review'));
  }

  const episodeReservations = getReservationsForEpisode(episode.id);
  const hasHolds = episodeReservations.some(r => r.status === 'HOLD');
  if (hasHolds) {
    return res.status(409).json(errorResponse('ERR_EPISODE_HAS_HOLDS', 'Cannot publish episode with HOLD reservations'));
  }

  const hasNeedsReview = episodeReservations.some(r => r.status === 'NEEDS_REVIEW');
  if (hasNeedsReview) {
    return res.status(409).json(errorResponse('ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS', 'Cannot publish episode with NEEDS_REVIEW reservations'));
  }

  const hasOverbooked = episodeReservations.some(r => r.status === 'OVERBOOKED');
  if (hasOverbooked) {
    return res.status(409).json(errorResponse('ERR_EPISODE_HAS_OVERBOOKED_RESERVATIONS', 'Cannot publish episode with OVERBOOKED reservations'));
  }

  episode.status = 'LIVE';
  episode.version++;

  const allReservations = getReservationsForEpisode(episode.id).map(r => ({
    id: r.id,
    deal_id: r.deal_id,
    placement: r.placement,
    slot_seconds: r.slot_seconds,
    status: r.status,
    script_version_pinned: r.script_version_pinned,
    version: r.version
  }));

  return res.status(200).json(successResponse({
    id: episode.id,
    podcast_id: episode.podcast_id,
    title: episode.title,
    content_rating: episode.content_rating,
    status: episode.status,
    clearance: getEpisodeClearance(episode.id),
    ad_slots_total_seconds: episode.ad_slots_total_seconds,
    ad_slots_held_seconds: getEpisodeAdHeldSeconds(episode.id),
    ad_slots_committed_seconds: getEpisodeAdCommittedSeconds(episode.id),
    reservations: allReservations,
    version: episode.version
  }));
});

app.post('/podcasts/:podcast_id/episodes/:episode_id/retract', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const episode = episodes.get(req.params.episode_id);

  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  if (String(episode.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (episode.status !== 'SUBMITTED' && episode.status !== 'LIVE') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Episode can only be retracted from SUBMITTED or LIVE status'));
  }

  const episodeReservations = getReservationsForEpisode(episode.id);
  const hasHolds = episodeReservations.some(r => r.status === 'HOLD');
  if (hasHolds) {
    return res.status(409).json(errorResponse('ERR_EPISODE_HAS_HOLDS', 'Cannot retract episode with HOLD reservations'));
  }

  retractEpisode(episode);

  const allReservations = getReservationsForEpisode(episode.id).map(r => ({
    id: r.id,
    deal_id: r.deal_id,
    placement: r.placement,
    slot_seconds: r.slot_seconds,
    status: r.status,
    script_version_pinned: r.script_version_pinned,
    version: r.version
  }));

  return res.status(200).json(successResponse({
    id: episode.id,
    podcast_id: episode.podcast_id,
    title: episode.title,
    content_rating: episode.content_rating,
    status: episode.status,
    clearance: getEpisodeClearance(episode.id),
    ad_slots_total_seconds: episode.ad_slots_total_seconds,
    ad_slots_held_seconds: getEpisodeAdHeldSeconds(episode.id),
    ad_slots_committed_seconds: getEpisodeAdCommittedSeconds(episode.id),
    reservations: allReservations,
    version: episode.version
  }));
});

app.post('/podcasts/:podcast_id/deals', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const { advertiser_name, brand_tier, budget_total_cents, slot_price_cents, script_text } = req.body;

  if (!advertiser_name || !brand_tier || budget_total_cents === undefined || slot_price_cents === undefined || !script_text) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required fields'));
  }

  if (!['FAMILY_SAFE', 'STANDARD'].includes(brand_tier)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'brand_tier must be FAMILY_SAFE or STANDARD'));
  }

  const deal: Deal = {
    id: generateId(),
    podcast_id: podcast.id,
    advertiser_name,
    brand_tier,
    budget_total_cents,
    slot_price_cents,
    script_text,
    script_version: 1,
    status: 'DRAFT',
    version: 1
  };

  deals.set(deal.id, deal);

  const held = getDealBudgetHeldCents(deal.id);
  const committed = getDealBudgetCommittedCents(deal.id);
  const spent = getDealBudgetSpentCents(deal.id);

  return res.status(201).json(successResponse({
    id: deal.id,
    podcast_id: deal.podcast_id,
    advertiser_name: deal.advertiser_name,
    brand_tier: deal.brand_tier,
    budget_total_cents: deal.budget_total_cents,
    slot_price_cents: deal.slot_price_cents,
    script_text: deal.script_text,
    script_version: deal.script_version,
    status: deal.status,
    budget_held_cents: held,
    budget_committed_cents: committed,
    budget_spent_cents: spent,
    budget_available_cents: Math.max(0, deal.budget_total_cents - held - committed - spent),
    version: deal.version
  }));
});

app.get('/podcasts/:podcast_id/deals/:deal_id', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const deal = deals.get(req.params.deal_id);

  if (!deal || deal.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Deal not found'));
  }

  const held = getDealBudgetHeldCents(deal.id);
  const committed = getDealBudgetCommittedCents(deal.id);
  const spent = getDealBudgetSpentCents(deal.id);

  return res.status(200).json(successResponse({
    id: deal.id,
    podcast_id: deal.podcast_id,
    advertiser_name: deal.advertiser_name,
    brand_tier: deal.brand_tier,
    budget_total_cents: deal.budget_total_cents,
    slot_price_cents: deal.slot_price_cents,
    script_text: deal.script_text,
    script_version: deal.script_version,
    status: deal.status,
    budget_held_cents: held,
    budget_committed_cents: committed,
    budget_spent_cents: spent,
    budget_available_cents: Math.max(0, deal.budget_total_cents - held - committed - spent),
    version: deal.version
  }));
});

app.put('/podcasts/:podcast_id/deals/:deal_id', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const deal = deals.get(req.params.deal_id);

  if (!deal || deal.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Deal not found'));
  }

  const newStatus = req.body.status;
  if (newStatus === 'ACTIVE' && getPodcastPosture(podcast) === 'RESTRICTED') {
    return res.status(403).json(errorResponse('ERR_PODCAST_RESTRICTED', 'Cannot activate deal while podcast is restricted'));
  }

  if (String(deal.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (newStatus === 'CLOSED' && deal.status !== 'CLOSED') {

    const dealReservations = getReservationsForDeal(deal.id);
    for (const reservation of dealReservations) {
      if (!isTerminalReservationStatus(reservation.status)) {
        reservation.status = 'CANCELED';
        reservation.version++;
      }
    }
  }

  const { advertiser_name, brand_tier, budget_total_cents, slot_price_cents, script_text, status } = req.body;

  const oldScriptText = deal.script_text;

  if (advertiser_name !== undefined) deal.advertiser_name = advertiser_name;
  if (brand_tier !== undefined) {
    if (!['FAMILY_SAFE', 'STANDARD'].includes(brand_tier)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'brand_tier must be FAMILY_SAFE or STANDARD'));
    }
    deal.brand_tier = brand_tier;
  }
  if (budget_total_cents !== undefined) deal.budget_total_cents = budget_total_cents;
  if (slot_price_cents !== undefined) deal.slot_price_cents = slot_price_cents;
  if (script_text !== undefined && script_text !== oldScriptText) {
    deal.script_text = script_text;
    deal.script_version++;

    const dealReservations = getReservationsForDeal(deal.id);
    for (const reservation of dealReservations) {
      if (reservation.status === 'APPROVED') {
        reservation.status = 'NEEDS_REVIEW';
        reservation.version++;
      }
    }
  }
  if (status !== undefined) {
    if (!['DRAFT', 'ACTIVE', 'PAUSED', 'CLOSED'].includes(status)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'status must be DRAFT, ACTIVE, PAUSED, or CLOSED'));
    }
    deal.status = status;
  }

  deal.version++;

  const held = getDealBudgetHeldCents(deal.id);
  const committed = getDealBudgetCommittedCents(deal.id);
  const spent = getDealBudgetSpentCents(deal.id);

  return res.status(200).json(successResponse({
    id: deal.id,
    podcast_id: deal.podcast_id,
    advertiser_name: deal.advertiser_name,
    brand_tier: deal.brand_tier,
    budget_total_cents: deal.budget_total_cents,
    slot_price_cents: deal.slot_price_cents,
    script_text: deal.script_text,
    script_version: deal.script_version,
    status: deal.status,
    budget_held_cents: held,
    budget_committed_cents: committed,
    budget_spent_cents: spent,
    budget_available_cents: Math.max(0, deal.budget_total_cents - held - committed - spent),
    version: deal.version
  }));
});

app.post('/podcasts/:podcast_id/reservations', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const { episode_id, deal_id, placement, slot_seconds } = req.body;

  if (!episode_id || !deal_id || !placement || slot_seconds === undefined) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required fields: episode_id, deal_id, placement, slot_seconds'));
  }

  if (!['PRE_ROLL', 'MID_ROLL', 'POST_ROLL'].includes(placement)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'placement must be PRE_ROLL, MID_ROLL, or POST_ROLL'));
  }

  const episode = episodes.get(episode_id);
  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  const deal = deals.get(deal_id);
  if (!deal || deal.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Deal not found'));
  }

  const existingReservation = getReservationsForEpisode(episode_id)
    .find(r => r.deal_id === deal_id && r.placement === placement && !isTerminalReservationStatus(r.status));

  if (existingReservation) {
    return res.status(409).json(errorResponse('ERR_DUPLICATE_RESERVATION', 'A reservation already exists for this episode, deal, and placement'));
  }

  const podcastHeld = getPodcastAdHeldSeconds(podcast.id);
  const podcastCommitted = getPodcastAdCommittedSeconds(podcast.id);
  const podcastAvailable = podcast.ad_capacity_seconds - podcastHeld - podcastCommitted;

  if (slot_seconds > podcastAvailable) {
    return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', 'Podcast ad capacity exceeded', { capacity_scope: 'PODCAST' }));
  }

  const episodeHeld = getEpisodeAdHeldSeconds(episode_id);
  const episodeCommitted = getEpisodeAdCommittedSeconds(episode_id);
  const episodeAvailable = episode.ad_slots_total_seconds - episodeHeld - episodeCommitted;

  if (slot_seconds > episodeAvailable) {
    return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', 'Episode ad capacity exceeded', { capacity_scope: 'EPISODE' }));
  }

  const dealHeld = getDealBudgetHeldCents(deal_id);
  const dealCommitted = getDealBudgetCommittedCents(deal_id);
  const dealSpent = getDealBudgetSpentCents(deal_id);
  const dealAvailable = deal.budget_total_cents - dealHeld - dealCommitted - dealSpent;

  if (deal.slot_price_cents > dealAvailable) {
    return res.status(409).json(errorResponse('ERR_DEAL_BUDGET_EXCEEDED', 'Deal budget exceeded'));
  }

  const reservation: Reservation = {
    id: generateId(),
    podcast_id: podcast.id,
    episode_id,
    deal_id,
    placement,
    slot_seconds,
    status: 'HOLD',
    script_version_pinned: null,
    version: 1,
    ops_run_at_creation: podcast.ops_run_index
  };

  reservations.set(reservation.id, reservation);

  return res.status(201).json(successResponse({
    id: reservation.id,
    podcast_id: reservation.podcast_id,
    episode_id: reservation.episode_id,
    deal_id: reservation.deal_id,
    placement: reservation.placement,
    slot_seconds: reservation.slot_seconds,
    status: reservation.status,
    script_version_pinned: reservation.script_version_pinned,
    version: reservation.version
  }));
});

app.post('/podcasts/:podcast_id/reservations/:reservation_id/approve', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const reservation = reservations.get(req.params.reservation_id);

  if (!reservation || reservation.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Reservation not found'));
  }

  if (getPodcastPosture(podcast) === 'RESTRICTED') {
    return res.status(403).json(errorResponse('ERR_PODCAST_RESTRICTED', 'Cannot approve while podcast is restricted'));
  }

  if (String(reservation.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (!['HOLD', 'NEEDS_REVIEW', 'OVERBOOKED'].includes(reservation.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Reservation cannot be approved from current status'));
  }

  const episode = episodes.get(reservation.episode_id);
  const deal = deals.get(reservation.deal_id);

  if (!episode || !deal) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode or deal not found'));
  }

  if (getEpisodeClearance(episode.id) === 'UNDER_REVIEW') {
    return res.status(409).json(errorResponse('ERR_EPISODE_UNDER_REVIEW', 'Cannot approve reservation on episode under review'));
  }

  if (deal.status !== 'ACTIVE') {
    return res.status(409).json(errorResponse('ERR_DEAL_NOT_ACTIVE', 'Deal must be ACTIVE to approve reservations'));
  }

  if (!checkBrandSafety(deal, episode)) {
    return res.status(409).json(errorResponse('ERR_BRAND_SAFETY_MISMATCH', 'FAMILY_SAFE deals cannot be approved on MATURE episodes'));
  }

  if (reservation.status === 'OVERBOOKED') {

    const podcastHeld = getPodcastAdHeldSeconds(podcast.id);
    const podcastCommitted = getPodcastAdCommittedSeconds(podcast.id);
    const podcastAvailable = podcast.ad_capacity_seconds - podcastHeld - podcastCommitted;

    if (reservation.slot_seconds > podcastAvailable) {
      return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', 'Podcast ad capacity exceeded', { capacity_scope: 'PODCAST' }));
    }

    const episodeHeld = getEpisodeAdHeldSeconds(episode.id);
    const episodeCommitted = getEpisodeAdCommittedSeconds(episode.id);
    const episodeAvailable = episode.ad_slots_total_seconds - episodeHeld - episodeCommitted;

    if (reservation.slot_seconds > episodeAvailable) {
      return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', 'Episode ad capacity exceeded', { capacity_scope: 'EPISODE' }));
    }

    const dealHeld = getDealBudgetHeldCents(deal.id);
    const dealCommitted = getDealBudgetCommittedCents(deal.id);
    const dealSpent = getDealBudgetSpentCents(deal.id);
    const dealAvailable = deal.budget_total_cents - dealHeld - dealCommitted - dealSpent;

    if (deal.slot_price_cents > dealAvailable) {
      return res.status(409).json(errorResponse('ERR_DEAL_BUDGET_EXCEEDED', 'Deal budget exceeded'));
    }
  }

  reservation.status = 'APPROVED';
  reservation.script_version_pinned = deal.script_version;
  reservation.version++;

  return res.status(200).json(successResponse({
    id: reservation.id,
    podcast_id: reservation.podcast_id,
    episode_id: reservation.episode_id,
    deal_id: reservation.deal_id,
    placement: reservation.placement,
    slot_seconds: reservation.slot_seconds,
    status: reservation.status,
    script_version_pinned: reservation.script_version_pinned,
    version: reservation.version
  }));
});

app.post('/podcasts/:podcast_id/reservations/:reservation_id/cancel', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const reservation = reservations.get(req.params.reservation_id);

  if (!reservation || reservation.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Reservation not found'));
  }

  if (String(reservation.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (!['HOLD', 'APPROVED', 'NEEDS_REVIEW', 'OVERBOOKED'].includes(reservation.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Reservation cannot be canceled from current status'));
  }

  reservation.status = 'CANCELED';
  reservation.version++;

  return res.status(200).json(successResponse({
    id: reservation.id,
    podcast_id: reservation.podcast_id,
    episode_id: reservation.episode_id,
    deal_id: reservation.deal_id,
    placement: reservation.placement,
    slot_seconds: reservation.slot_seconds,
    status: reservation.status,
    script_version_pinned: reservation.script_version_pinned,
    version: reservation.version
  }));
});

app.post('/podcasts/:podcast_id/reservations/:reservation_id/settle', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const reservation = reservations.get(req.params.reservation_id);

  if (!reservation || reservation.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Reservation not found'));
  }

  if (String(reservation.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (reservation.status !== 'APPROVED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Reservation can only be settled from APPROVED status'));
  }

  const episode = episodes.get(reservation.episode_id);
  const deal = deals.get(reservation.deal_id);

  if (!episode || !deal) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode or deal not found'));
  }

  if (episode.status !== 'LIVE') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Episode must be LIVE to settle reservations'));
  }

  if (getEpisodeClearance(episode.id) === 'UNDER_REVIEW') {
    return res.status(409).json(errorResponse('ERR_EPISODE_UNDER_REVIEW', 'Cannot settle reservation on episode under review'));
  }

  if (deal.status !== 'ACTIVE') {
    return res.status(409).json(errorResponse('ERR_DEAL_NOT_ACTIVE', 'Deal must be ACTIVE to settle reservations'));
  }

  reservation.status = 'SETTLED';
  reservation.version++;

  return res.status(200).json(successResponse({
    id: reservation.id,
    podcast_id: reservation.podcast_id,
    episode_id: reservation.episode_id,
    deal_id: reservation.deal_id,
    placement: reservation.placement,
    slot_seconds: reservation.slot_seconds,
    status: reservation.status,
    script_version_pinned: reservation.script_version_pinned,
    version: reservation.version
  }));
});

app.post('/podcasts/:podcast_id/claims', (req: Request, res: Response) => {
  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const { episode_id, kind } = req.body;

  if (!episode_id || !kind) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required fields: episode_id, kind'));
  }

  if (!['RIGHTS', 'BRAND_SAFETY'].includes(kind)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'kind must be RIGHTS or BRAND_SAFETY'));
  }

  const episode = episodes.get(episode_id);
  if (!episode || episode.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Episode not found'));
  }

  const existingClaim = getClaimsForEpisode(episode_id)
    .find(c => c.kind === kind && c.status === 'OPEN');

  if (existingClaim) {
    return res.status(409).json(errorResponse('ERR_DUPLICATE_CLAIM', 'An open claim of this kind already exists for this episode'));
  }

  const claim: Claim = {
    id: generateId(),
    podcast_id: podcast.id,
    episode_id,
    kind,
    status: 'OPEN',
    outcome: null,
    version: 1
  };

  claims.set(claim.id, claim);

  return res.status(201).json(successResponse({
    id: claim.id,
    podcast_id: claim.podcast_id,
    episode_id: claim.episode_id,
    kind: claim.kind,
    status: claim.status,
    outcome: claim.outcome,
    version: claim.version
  }));
});

app.post('/podcasts/:podcast_id/claims/:claim_id/close', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];

  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const podcast = podcasts.get(req.params.podcast_id);

  if (!podcast) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Podcast not found'));
  }

  const claim = claims.get(req.params.claim_id);

  if (!claim || claim.podcast_id !== podcast.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Claim not found'));
  }

  if (String(claim.version) !== String(ifMatch)) {
    return res.status(412).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (claim.status !== 'OPEN') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Claim is already closed'));
  }

  const { outcome } = req.body;

  if (!outcome || !['ACCEPTED', 'REJECTED', 'WITHDRAWN'].includes(outcome)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'outcome must be ACCEPTED, REJECTED, or WITHDRAWN'));
  }

  claim.status = 'CLOSED';
  claim.outcome = outcome;
  claim.version++;

  if (outcome === 'ACCEPTED') {
    podcast.had_accepted_claim = true;

    const episode = episodes.get(claim.episode_id);
    if (episode && episode.status !== 'RETRACTED') {

      retractEpisode(episode);
    }
  }

  return res.status(200).json(successResponse({
    id: claim.id,
    podcast_id: claim.podcast_id,
    episode_id: claim.episode_id,
    kind: claim.kind,
    status: claim.status,
    outcome: claim.outcome,
    version: claim.version
  }));
});

app.use((req: Request, res: Response) => {
  res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Endpoint not found'));
});

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error(err);
  res.status(500).json(errorResponse('ERR_BAD_REQUEST', 'Internal server error'));
});

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`PodReserve API listening on port ${PORT}`);
});

export default app;

import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Listing, CONSTANTS } from '../types';
import {
  successResponse, sendError, ERRORS,
  validateCategory, getListingPriorityTier
} from '../utils';

const router = Router({ mergeParams: true });

router.post('/', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const {
    title,
    category,
    base_price_cents,
    surge_multiplier,
    customer_sla_periods,
    max_parallel_assignments
  } = req.body;

  if (!title || typeof title !== 'string' || title.trim() === '') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'title is required');
  }

  if (!category || !validateCategory(category)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Invalid category');
  }

  if (base_price_cents === undefined ||
      typeof base_price_cents !== 'number' ||
      base_price_cents < 0 ||
      !Number.isInteger(base_price_cents)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'base_price_cents must be a non-negative integer');
  }

  if (surge_multiplier === undefined ||
      typeof surge_multiplier !== 'number' ||
      surge_multiplier < 1.0) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'surge_multiplier must be >= 1.0');
  }

  if (customer_sla_periods === undefined ||
      typeof customer_sla_periods !== 'number' ||
      customer_sla_periods < 1 ||
      !Number.isInteger(customer_sla_periods)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'customer_sla_periods must be a positive integer');
  }

  if (max_parallel_assignments === undefined ||
      typeof max_parallel_assignments !== 'number' ||
      max_parallel_assignments < 1 ||
      !Number.isInteger(max_parallel_assignments)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'max_parallel_assignments must be a positive integer');
  }

  const id = uuidv4();
  const createdSeq = getNextSeq(tenantId);

  const listing: Listing = {
    id,
    tenant_id: tenantId,
    title: title.trim(),
    category,
    base_price_cents,
    surge_multiplier,
    customer_sla_periods,
    max_parallel_assignments,
    status: 'DRAFT',
    completed_order_count: 0,
    cancellation_rate_percent: 0,
    average_rating: 0,
    priority_tier: 0,
    created_seq: createdSeq
  };

  listing.priority_tier = getListingPriorityTier(listing);

  storage.saveListing(listing);
  return successResponse(res, listing, 201);
});

router.get('/', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listings = storage.getListingsByTenant(tenantId);
  return successResponse(res, listings);
});

router.get('/:listingId', (req: Request, res: Response) => {
  const { tenantId, listingId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listing = storage.getListing(listingId);

  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  return successResponse(res, listing);
});

router.put('/:listingId', (req: Request, res: Response) => {
  const { tenantId, listingId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listing = storage.getListing(listingId);

  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (listing.status === 'ARCHIVED') {
    return sendError(res, ERRORS.ERR_LISTING_NOT_EDITABLE);
  }

  const {
    title,
    category,
    base_price_cents,
    surge_multiplier,
    customer_sla_periods,
    max_parallel_assignments
  } = req.body;

  if (title !== undefined) {
    if (typeof title !== 'string' || title.trim() === '') {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'title must be a non-empty string');
    }
    listing.title = title.trim();
  }

  if (category !== undefined) {
    if (!validateCategory(category)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Invalid category');
    }
    listing.category = category;
    listing.priority_tier = getListingPriorityTier(listing);
  }

  if (base_price_cents !== undefined) {
    if (typeof base_price_cents !== 'number' ||
        base_price_cents < 0 ||
        !Number.isInteger(base_price_cents)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'base_price_cents must be a non-negative integer');
    }
    listing.base_price_cents = base_price_cents;
  }

  if (surge_multiplier !== undefined) {
    if (typeof surge_multiplier !== 'number' || surge_multiplier < 1.0) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'surge_multiplier must be >= 1.0');
    }
    listing.surge_multiplier = surge_multiplier;
  }

  if (customer_sla_periods !== undefined) {
    if (typeof customer_sla_periods !== 'number' ||
        customer_sla_periods < 1 ||
        !Number.isInteger(customer_sla_periods)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'customer_sla_periods must be a positive integer');
    }
    listing.customer_sla_periods = customer_sla_periods;
  }

  if (max_parallel_assignments !== undefined) {
    if (typeof max_parallel_assignments !== 'number' ||
        max_parallel_assignments < 1 ||
        !Number.isInteger(max_parallel_assignments)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'max_parallel_assignments must be a positive integer');
    }
    listing.max_parallel_assignments = max_parallel_assignments;
  }

  storage.saveListing(listing);
  return successResponse(res, listing);
});

router.post('/:listingId/publish', (req: Request, res: Response) => {
  const { tenantId, listingId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listing = storage.getListing(listingId);

  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (listing.status !== 'DRAFT') {
    return sendError(res, ERRORS.ERR_LISTING_NOT_DRAFT);
  }

  listing.status = 'PUBLISHED';
  storage.saveListing(listing);
  return successResponse(res, listing);
});

router.post('/:listingId/pause', (req: Request, res: Response) => {
  const { tenantId, listingId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listing = storage.getListing(listingId);

  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (listing.status !== 'PUBLISHED') {
    return sendError(res, ERRORS.ERR_LISTING_NOT_PUBLISHED);
  }

  listing.status = 'PAUSED';
  storage.saveListing(listing);
  return successResponse(res, listing);
});

router.post('/:listingId/resume', (req: Request, res: Response) => {
  const { tenantId, listingId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listing = storage.getListing(listingId);

  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (listing.status !== 'PAUSED') {
    return sendError(res, ERRORS.ERR_LISTING_NOT_PAUSED);
  }

  listing.status = 'PUBLISHED';
  storage.saveListing(listing);
  return successResponse(res, listing);
});

router.post('/:listingId/archive', (req: Request, res: Response) => {
  const { tenantId, listingId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const listing = storage.getListing(listingId);

  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (listing.status === 'ARCHIVED') {
    return sendError(res, ERRORS.ERR_LISTING_ALREADY_ARCHIVED);
  }

  if (listing.status !== 'PUBLISHED' && listing.status !== 'PAUSED') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Only published or paused listings can be archived');
  }

  listing.status = 'ARCHIVED';
  storage.saveListing(listing);
  return successResponse(res, listing);
});

export default router;

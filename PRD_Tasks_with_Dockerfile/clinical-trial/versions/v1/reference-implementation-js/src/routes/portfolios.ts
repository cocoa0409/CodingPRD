import { Router } from 'express';
import { db } from '../database';
import { LedgerService } from '../services/ledgers';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly, anyRole } from '../middleware/auth';
import { validateVersionIfProvided } from '../utils/occ';

const router = Router({ mergeParams: true });

router.post(
  '/',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const { name, description, max_total_ethical_budget } = req.body;

    const portfolio = db.createPortfolio({
      research_program_id: programId,
      name,
      description,
      max_total_ethical_budget
    });

    LedgerService.recomputePortfolioSaturation(portfolio.id);

    res.status(201).json(
      wrapResponse('object', portfolio, getResponseMeta(req))
    );
  })
);

router.get(
  '/',
  anyRole,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const portfolios = db.listPortfolios(programId);

    res.status(200).json(
      wrapResponse('array', portfolios, getResponseMeta(req))
    );
  })
);

router.get(
  '/:portfolioId',
  anyRole,
  asyncHandler(async (req, res) => {
    const { portfolioId } = req.params;
    const portfolio = db.getPortfolio(portfolioId);

    res.status(200).json(
      wrapResponse('object', portfolio, getResponseMeta(req))
    );
  })
);

router.put(
  '/:portfolioId',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { portfolioId } = req.params;
    const { name, description, max_total_ethical_budget } = req.body;

    const portfolio = db.getPortfolio(portfolioId);

    validateVersionIfProvided(req, portfolio.version);

    if (name !== undefined) portfolio.name = name;
    if (description !== undefined) portfolio.description = description;
    if (max_total_ethical_budget !== undefined) {
      portfolio.max_total_ethical_budget = max_total_ethical_budget;
    }

    portfolio.version++;
    portfolio.updated_at = new Date().toISOString();

    LedgerService.recomputePortfolioSaturation(portfolioId);

    res.status(200).json(
      wrapResponse('object', portfolio, getResponseMeta(req))
    );
  })
);

export default router;
